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
    def __init__(self, api_key=None, model=None):
        self.base_url = None
        self.api_key = api_key
        self.model = model
        self.base_url = None
        self.port=""
        self.ctx_size=4096

    def get_client(self):
        raise NotImplementedError


class OllamaApiEndpoint(APIEndpoint):
    def __init__(self, api_key=None, model=None):

        super().__init__(api_key, model)
        host_ip = get_gateway_ip()
        self.port = os.getenv("OLLAMA_PORT", "11434")
        self.base_url = os.getenv("OLLAMA_BASE_URL", f"http://{host_ip}:{self.port}/v1")

    def get_client(self):
        self.model = self.model or "gemma4:31b-cloud"
        #model = os.getenv("AGENT_MODEL", "beam:cloud")
        return OpenAI(base_url=self.base_url, api_key="ollama"), self.model

class MistralAPIEndpoint(APIEndpoint):
    def __init__(self,api_key=None, model=None):
        super().__init__(api_key, model)
        self.base_url = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
        self.ctx_size=32000

    def get_client(self):
        api_key = os.getenv("MISTRAL_API_KEY", self.api_key)
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY not set.")
        self.model = self.model or "ministral-14b-latest"
        logger.info (f"mistral model: {model}")
        return OpenAI(base_url=self.base_url, api_key=api_key), self.model


class LLMBackend:
    def __init__(self, backend="mistral"):
        self.backend = backend
        self.usage = UsageTracker()
        self.model = os.getenv("AGENT_MODEL", "")
        logger.info(f"Backend: {backend}, Model: {self.model}")

    def set_model(self, model):
        self.model = model

    def select_backend(self, backend):
        self.backend = backend
        backend_map = {
            "ollama": OllamaApiEndpoint,
            "mistral": MistralAPIEndpoint
        }
        try:
            return backend_map[backend]
        except KeyError:
            raise ValueError(f"Unsupported backend: {backend}")

    def get_client(self) -> tuple[OpenAI, str]:
        usage = self.usage
        # logger = logging.getLogger("UnifiedAgent")   # was setup_logging(...)
        logger.info(f"context window: {usage.context_limit} (model max may be larger)")
        try:
            endpoint = self.select_backend(self.backend)(None, self.model)
            context_size = endpoint.ctx_size
            usage.context_limit = discover_context_window(
                endpoint.base_url, model=self.model, default=context_size, backend=self.backend)
            return endpoint(base_url=None, api_key="ollama", model=self.model).get_client()
        except KeyError:
            raise ValueError(f"Unsupported backend: {self.backend}")


if __name__=="__main__":
    from pprint import pprint
    llm_backend = LLMBackend(backend="mistral")
    llm_backend.set_model("ministral-14b-latest")
    client, model = llm_backend.get_client()
    print(model)
    response = client.chat.completions.create(
        model=llm_backend.model,
        messages=[
            {"role": "user", "content": "What is Mistral AI?"}
            ],
        tools=[],
        tool_choice="auto"
    )
    pprint(response)