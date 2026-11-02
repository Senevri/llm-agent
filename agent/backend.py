import os
import httpx2 as requests
from urllib.parse import urlparse, urlsplit
from openai import OpenAI
from get_ip import get_gateway_ip
from llm_utils import UsageTracker, discover_context_window
from custom_logger import setup_logging
from dotenv import load_dotenv
from typing import Optional, Dict, Type
from pathlib import Path

AGENT_DIR = os.getenv("AGENT_DIR", "/agent")
if not Path(AGENT_DIR).exists():
    AGENT_DIR = Path(__file__).resolve().parent
load_dotenv(f"{AGENT_DIR}/.env")

if not Path("/workspace").exists():
    LOG_DIR = Path.cwd() / "logs/"
else:
    LOG_DIR = os.getenv("LOG_DIR", "/workspace/logs/")

logger = setup_logging("Backend", level="INFO", log_dir=Path(LOG_DIR))


class APIEndpoint:
    """Base class for LLM API endpoints."""
    def __init__(self, model: str = "", base_url: str = ""):
        self.model = model
        self.base_url = base_url

        self.api_key = ""
        self.ctx_size = 4096  # Sensible default fallback

    def get_models(self) -> list[str]:
        raise NotImplementedError("Subclasses must implement get_models()")

    def get_client(self) -> tuple[OpenAI, str]:
        raise NotImplementedError("Subclasses must implement get_client()")

    def set_base_url(self, base_url, port=None):
        #parsed = urlsplit(base_url)
        #print (f"Setting base URL to {base_url} with port {port}")
        logger.info(f"Setting base URL to {base_url} with port {port}")
        parsed = urlparse(base_url)

        if not port:
            raise ValueError("Port is required")

        base_url =  parsed.netloc.split(":")[0] or parsed.netloc
        parsed = parsed._replace(netloc=f"{base_url}:{port}")
        # parsed = parsed._replace(port=port)

        self.base_url = parsed.geturl()
        logger.info (f"Set base url to {self.base_url}")
        # raise Exception("debugging")

class RawEndpoint(APIEndpoint):

    def __init__(self, model: str = "", base_url: str = "http://localhost"):

        super().__init__(model, base_url)
        self.api_key = "00000000"
        self.ctx_size = 4096  # Sensible default fallback
        self.model = model
        self.try_get_model()

    def get_client(self) -> tuple[OpenAI, str]:
        return OpenAI(base_url=f"{self.base_url}/v1", api_key=self.api_key), self.model

    def get_model(self):
        return self.try_get_model()

    def try_get_model(self) -> str:
        self_model = self.model or ""
        try:
            response = requests.get(f"{self.base_url}/models", timeout=5)
            response.raise_for_status()
            models_data = response.json().get("data", [])
            available_models = [m.get("id") for m in models_data if "id" in m]
            self.model = next((m for m in available_models if m.startswith(self_model)), self.model)
        except Exception as e:
            logger.error(f"Failed to retrieve models from {self.base_url}: {e}")
        try:
            url = self.base_url.removesuffix("/v1")  + "/api/v1/model"
            current_model = requests.get(url)
            if current_model:
                self.model = current_model.json().get("result", self.model)
        except Exception as e:
            logger.error(f"Failed to retrieve current model from {self.base_url}: {e}")
        try:
            url = self.base_url.removesuffix("/v1")  + "/models"
            models = requests.get(url)
            models = models.json()["models"]
            model_names = [model["name"] for model in models]
            if self.model not in model_names:
                print(f"Setting default model to {models[0]['name']}")
                self.model = models[0]["model"]
        except Exception as e:
            logger.error(f"Failed to retrieve available models from {self.base_url}: {e}")

        return self.model


class KoboldCppApiendpoint(APIEndpoint):
    def __init__(self, model: str = "", base_url: str = ""):
        super().__init__(model, base_url)
        if not base_url:
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
    def __init__(self, model: str = "", base_url: str = ""):
        super().__init__(model, base_url)
        port = os.getenv("LLAMA_PORT", "9964")
        if not base_url:
            host_ip = get_gateway_ip()
            self.base_url = os.getenv(
                "LLAMA_BASE_URL",
                f"http://{host_ip}:{port}/v1"
        ).rstrip("/")
        if os.getenv("DEBUG", "false").lower() == "true":
            print(self.base_url)
        self.api_key = "llama"
        # Can be overwritten by args
        self.ctx_size = 32768
        # Empty means resolve the model from the server.
        self.model = model

    def get_context_size(self) -> int:
        url = self.base_url.removesuffix("/v1") + "/props"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        props = response.json()
        return props["default_generation_settings"]["n_ctx"]

    def get_client(self) -> tuple[OpenAI, str]:
        self.set_default_model()
        self.ctx_size = self.get_context_size()
        return OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        ), self.model

    def get_model(self):
        if not self.model:
            self.set_default_model()
        return self.model

    def set_default_model(self):
        models = self.get_llama_models()
        if not models:
            logger.warning("No models found from LLaMA endpoint.")
            return
        model_names = [model["name"] for model in models]
        if self.model not in model_names:
            print(f"Setting default model to {models[0]['name']}")
            self.model = models[0]["model"]

    def get_llama_models(self):
        # /api/v1/model
        if not self.base_url:
            return []
        available_models = requests.get(self.base_url + "/models")
        # format: {"result": "<model_name
        return available_models.json().get("models", [])

class OllamaApiEndpoint(APIEndpoint):
    def __init__(self, model: str = "", base_url: str = ""):
        super().__init__(model, base_url)
        port = os.getenv("OLLAMA_PORT", "11434")

        if not base_url:
            host_ip = get_gateway_ip()
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
        # /apimodel
        current_model = requests.get(self.base_url + "/api/v1/model")
        # format: {"result": "<model_name>"}
        return current_model.json()["result"]


class MistralApiEndpoint(APIEndpoint):
    def __init__(self, model: str = "", base_url: str = ""):
        super().__init__(model, base_url=base_url)
        self.base_url = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
        self.ctx_size = 32000
        self.model = self.model or "ministral-14b-latest"
        self.api_key = os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise RuntimeError("MISTRAL_API_KEY not set.")


    def get_client(self) -> tuple[OpenAI, str]:
        logger.info(f"Mistral model resolved to: {self.model}")
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model


BACKEND_MAP: Dict[str, Type[APIEndpoint]] = {
            "ollama": OllamaApiEndpoint,
            "mistral": MistralApiEndpoint,
            "koboldcpp": KoboldCppApiendpoint,
            "llamacpp": LlamaApiEndpoint,
            "raw": RawEndpoint
        }


class LLMBackend:
    def __init__(self, backend: str = "mistral"):
        self.backend = backend
        self.usage = UsageTracker()
        self.model = os.getenv("AGENT_MODEL", "")
        logger.info(f"Backend: {backend}, Model: {self.model or '(default)'}")
        self.backends = BACKEND_MAP.keys()
        self.port: Optional[int] = None
        self.endpoint: Optional[APIEndpoint] = None
        self.context_limit = -1
        self.base_url=""
        self.logger = logger

    def set_model(self, model: str):
        self.model = model

    def _get_endpoint(self):

        endpoint_cls: Optional[Type[APIEndpoint]] = BACKEND_MAP.get(self.backend)
        if not endpoint_cls:
            raise ValueError(f"Unsupported backend: {self.backend}")

        # 1. Instantiate the specific endpoint with the current model state
        self.endpoint = endpoint_cls(model=self.model, base_url=self.base_url)

        if self.port:
            # print(dict(endpoint_cls))
            self.endpoint.set_base_url(self.endpoint.base_url, self.port)
            logger.info(f"Adjusted base URL to: {self.endpoint.base_url}")
        return self.endpoint


    def get_client(self) -> tuple[OpenAI, str]:
        """Initializes the correct endpoint, discovers context, and returns the client."""

        endpoint = self._get_endpoint()
        self.model = self.endpoint.model
        # 2. Discover context window (this updates the usage tracker)
        # Note: Removed `backend=self.backend` kwarg unless your discover_context_window explicitly requires it
        try:
            self.usage.context_limit = discover_context_window(
                self.endpoint.base_url,
                model=self.endpoint.model,
                default=self.endpoint.ctx_size,
                backend=self.backend
            )
            #logger.warn(self.usage.context_limit)
        except Exception as e:
            logger.error(f"Error discovering context window: {e}")
            logger.error(
                f"Values: base_url={self.endpoint.base_url}, "
                f"model={self.endpoint.model}, "
                f"default={self.endpoint.ctx_size}, "
                f"backend={self.backend}")
            self.usage.context_limit = self.endpoint.ctx_size  # Fallback to default
        logger.info(f"Context window set to: {self.usage.context_limit}")
        self.context_limit = self.usage.context_limit

        # 3. Return the configured client and the fully-resolved model name
        client, resolved_model = self.endpoint.get_client()
        # print(resolved_model)
        self.model = resolved_model

        return client, resolved_model
        # return endpoint.get_client()


if __name__ == "__main__":
    from pprint import pprint
    from argparse import ArgumentParser


    defaultbackend = os.getenv("AGENT_BACKEND", "llamacpp")
    parser = ArgumentParser()
    parser.add_argument("--backend", type=str, default=defaultbackend, help="LLM backend to use (ollama, mistral, koboldcpp, llamacpp)")
    parser.add_argument("--model", type=str, default="", help="Model name to use (if applicable)")
    parser.add_argument("--port", type=int, default="5001", help="Port for the backend service (if applicable)")
    args=parser.parse_args()

    # backend="mistral"
    # model="ministral-14b-latest"

    llm_backend = LLMBackend(backend=args.backend)
    llm_backend.port = args.port


    if args.model:
        llm_backend.set_model(args.model)

    llm_backend._get_endpoint()
    print(f"Context window: {llm_backend.context_limit} tokens")
    llm_backend.context_limit = discover_context_window(
        llm_backend.endpoint.base_url,
        model=llm_backend.endpoint.model,
        default=llm_backend.endpoint.ctx_size,
        backend=llm_backend.backend)
    client, resolved_model = llm_backend.get_client()
    print(f"Using model: {resolved_model}")
    print(f"Base URL: {str(llm_backend.endpoint.base_url)}")
    print(f"Context window: {llm_backend.context_limit} tokens")
    exit(0)
    # msg = "What is Mistral AI?"
    msg = "Tell me about yourself concisely in tweet length."

    response = client.chat.completions.create(
        model=resolved_model,
        messages=[{"role": "user", "content": msg}],
        tools=[],
        tool_choice="auto"
    )
    pprint(response)