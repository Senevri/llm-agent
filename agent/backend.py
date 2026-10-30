import os
import requests
from urllib.parse import urlparse, urlsplit
from openai import OpenAI
from get_ip import get_gateway_ip
from llm_utils import UsageTracker, discover_context_window
from custom_logger import setup_logging
from dotenv import load_dotenv
from typing import Optional

AGENT_DIR = os.getenv("AGENT_DIR", "/agent")
load_dotenv(f"{AGENT_DIR}/.env")

logger = setup_logging("INFO")


class APIEndpoint:
    """Base class for LLM API endpoints."""
    def __init__(self, model: str = ""):
        self.model = model
        self.base_url = ""
        self.api_key = ""
        self.ctx_size = 4096  # Sensible default fallback

    def get_models(self) -> list[str]:
        raise NotImplementedError("Subclasses must implement get_models()")

    def get_client(self) -> tuple[OpenAI, str]:
        raise NotImplementedError("Subclasses must implement get_client()")

    def set_base_url(self, base_url, port=None):
        #parsed = urlsplit(base_url)
        parsed = urlparse(base_url)

        if not port:
            raise ValueError("Port is required")

        base_url =  parsed.netloc.split(":")[0] or parsed.netloc
        parsed = parsed._replace(netloc=f"{base_url}:{port}")
        # parsed = parsed._replace(port=port)

        self.base_url = parsed.geturl()
        logger.info (f"Set base url to {self.base_url}")
        # raise Exception("debugging")

class RawEndpoint:
    def get_client(self) -> tuple[OpenAI, str]:
        raise NotImplementedError("Subclasses must implement get_client()")

class KoboldCppApiendpoint(APIEndpoint):
    def __init__(self, model: str = ""):
        super().__init__(model)
        host_ip = get_gateway_ip()
        self.base_url = os.getenv("KOBOLD_BASE_URL", f"http://{host_ip}:5001/")
        self.ctx_size = 8192
        self.api_key = "kobold"
        try:
            self.model = self.get_kobold_model()
            self.ctx_size = self.get_kobold_ctx()
        except Exception as e:
            logger.error(f"Failed to get Kobold model: {e}")
            self.model = ""

    def get_kobold_ctx(self):
        # /api/extra/true_max_context_length
        current_ctx = requests.get(self.base_url + "/api/extra/true_max_context_length")
        return current_ctx.json()["value"]

    def get_models(self):
        self.get_kobold_model()

    def get_kobold_model(self):
        # /api/v1/model
        current_model = requests.get(self.base_url + "/api/v1/model")
        # format: {"result": "<model_name>"}
        return current_model.json()["result"]

    def get_client(self) -> tuple[OpenAI, str]:
        # Return openapi compatible way for now
        return OpenAI(base_url=f"{self.base_url}/v1", api_key=self.api_key), self.model

class LlamaApiEndpoint(APIEndpoint):

    def __init__(self, model: str = ""):
        super().__init__(model)
        host_ip = get_gateway_ip()
        port = os.getenv("LLAMA_PORT", "9964")
        self.base_url = os.getenv("LLAMA_BASE_URL", f"http://{host_ip}:{port}/v1")
        self.api_key = "llama"
        self.ctx_size = 8192  # Llama default, but will be overwritten by discovery
        self.model = self.model or "llama-7b"

    def get_client(self) -> tuple[OpenAI, str]:
        # Resolve default model at the last possible moment
        self.set_default_model()

        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model

    def get_model(self):
        return self.model

    def set_default_model(self):
        models = self.get_llama_models()
        model_names = [model["name"] for model in models]
        if self.model not in model_names:
            print(f"Setting default model to {models[0]['name']}")
            self.model = models[0]["model"]

    def get_llama_models(self):
        # /api/v1/model
        available_models = requests.get(self.base_url + "/v1/models")
        # format: {"result": "<model_name
        return available_models.json()["models"]

class OllamaApiEndpoint(APIEndpoint):
    def __init__(self, model: str = ""):
        super().__init__(model)
        host_ip = get_gateway_ip()
        port = os.getenv("OLLAMA_PORT", "11434")
        self.base_url = os.getenv("OLLAMA_BASE_URL", f"http://{host_ip}:{port}/v1")
        self.api_key = "ollama"
        self.ctx_size = 8192  # Ollama default, but will be overwritten by discovery
        self.model = self.model or "gemma4:31b-cloud"

    def get_client(self) -> tuple[OpenAI, str]:
        # Resolve default model at the last possible moment
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model

    def get_model(self):
        self.model = self.get_ollama_model()

    def get_ollama_model(self):
        # /api/v1/model
        current_model = requests.get(self.base_url + "/api/v1/model")
        # format: {"result": "<model_name>"}
        return current_model.json()["result"]


class MistralApiEndpoint(APIEndpoint):
    def __init__(self, model: str = ""):
        super().__init__(model)
        self.base_url = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
        self.ctx_size = 32000
        self.model = self.model or "ministral-14b-latest"
        self.api_key = os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise RuntimeError("MISTRAL_API_KEY not set.")


    def get_client(self) -> tuple[OpenAI, str]:
        logger.info(f"Mistral model resolved to: {self.model}")
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model


BACKEND_MAP = {
            "ollama": OllamaApiEndpoint,
            "mistral": MistralApiEndpoint,
            "koboldcpp": KoboldCppApiendpoint,
            "llamacpp": LlamaApiEndpoint
        }


class LLMBackend:
    def __init__(self, backend: str = "mistral"):
        self.backend = backend
        self.usage = UsageTracker()
        self.model = os.getenv("AGENT_MODEL", "")
        logger.info(f"Backend: {backend}, Model: {self.model or '(default)'}")
        self.backends = BACKEND_MAP.keys()
        self.port: Optional[int] = None

    def set_model(self, model: str):
        self.model = model

    def get_client(self) -> tuple[OpenAI, str]:
        """Initializes the correct endpoint, discovers context, and returns the client."""

        endpoint_cls: APIEndpoint = BACKEND_MAP.get(self.backend)
        if not endpoint_cls:
            raise ValueError(f"Unsupported backend: {self.backend}")

        # 1. Instantiate the specific endpoint with the current model state
        endpoint = endpoint_cls(model=self.model)

        if self.port:
            # print(dict(endpoint_cls))
            endpoint.set_base_url(endpoint.base_url, self.port)
            logger.info(f"Adjusted base URL to: {endpoint.base_url}")


        self.model = endpoint.model
        # 2. Discover context window (this updates the usage tracker)
        # Note: Removed `backend=self.backend` kwarg unless your discover_context_window explicitly requires it
        self.usage.context_limit = discover_context_window(
            endpoint.base_url,
            model=endpoint.model,
            default=endpoint.ctx_size
        )
        logger.info(f"Context window set to: {self.usage.context_limit}")

        # 3. Return the configured client and the fully-resolved model name
        client, resolved_model = endpoint.get_client()
        # print(resolved_model)
        self.model = resolved_model

        return client, resolved_model
        # return endpoint.get_client()


if __name__ == "__main__":
    from pprint import pprint


    # backend="mistral"
    # model="ministral-14b-latest"
    backend="koboldcpp"
    model=""

    llm_backend = LLMBackend(backend=backend)
    llm_backend.set_model(model)

    client, resolved_model = llm_backend.get_client()
    print(f"Using model: {resolved_model}")
    # msg = "What is Mistral AI?"
    msg = "What is Kobold AI?"

    response = client.chat.completions.create(
        model=resolved_model,
        messages=[{"role": "user", "content": msg}],
        tools=[],
        tool_choice="auto"
    )
    pprint(response)