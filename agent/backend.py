import os
from openai import OpenAI
from get_ip import get_gateway_ip
from llm_utils import UsageTracker, discover_context_window
from custom_logger import setup_logging
from dotenv import load_dotenv

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

    def get_client(self) -> tuple[OpenAI, str]:
        raise NotImplementedError("Subclasses must implement get_client()")


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


class MistralAPIEndpoint(APIEndpoint):
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


class LLMBackend:
    def __init__(self, backend: str = "mistral"):
        self.backend = backend
        self.usage = UsageTracker()
        self.model = os.getenv("AGENT_MODEL", "")
        logger.info(f"Backend: {backend}, Model: {self.model or '(default)'}")

    def set_model(self, model: str):
        self.model = model

    def get_client(self) -> tuple[OpenAI, str]:
        """Initializes the correct endpoint, discovers context, and returns the client."""
        backend_map = {
            "ollama": OllamaApiEndpoint,
            "mistral": MistralAPIEndpoint
        }

        endpoint_cls = backend_map.get(self.backend)
        if not endpoint_cls:
            raise ValueError(f"Unsupported backend: {self.backend}")

        # 1. Instantiate the specific endpoint with the current model state
        endpoint = endpoint_cls(model=self.model)
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
        return endpoint.get_client()


if __name__ == "__main__":
    from pprint import pprint

    llm_backend = LLMBackend(backend="mistral")
    llm_backend.set_model("ministral-14b-latest")

    client, resolved_model = llm_backend.get_client()
    print(f"Using model: {resolved_model}")

    response = client.chat.completions.create(
        model=resolved_model,
        messages=[{"role": "user", "content": "What is Mistral AI?"}],
        tools=[],
        tool_choice="auto"
    )
    pprint(response)