import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, Type, Optional, List, Any

import httpx2
from openai import OpenAI

SCRIPT_DIR = Path(__file__).resolve().parent.parent

if SCRIPT_DIR not in sys.path:
    sys.path.append(str(SCRIPT_DIR))

from custom_logger import setup_logging
from model_catalog import MODEL_CATALOGS
from get_ip import get_gateway_ip
from endpoint_config import BackendConfig, ProxyConfig

logger = setup_logging(__name__) # Could use unifiedagent

class APIError(Exception):
    pass

# api_endpoint.py  (additions only)
class APIEndpoint:
    DEFAULTS: Dict[str, Any] = {}        # subclasses override
    REQUIRED_ENV: List[str] = []

    def __init__(self, model="", base_url="", port="443", **_):
        self.model = model
        self.base_url = base_url
        self.port = port
        self.api_key = ""
        self.available_models: list[str] = []
        self.rate_limits: Dict[str, Any] = {}
        self.ctx_size: int = 4096
        self.timeout: int = 60
        self.extra = {}

    @classmethod
    def from_config(cls, cfg: BackendConfig) -> "APIEndpoint":
        merged = {**cls.DEFAULTS}
        for k in ("base_url", "port", "ctx_size"):
            v = getattr(cfg, k)
            if v not in ("", None): merged[k] = v

        api_key = cfg.api_key or os.getenv(cls.REQUIRED_ENV[0], "") if cls.REQUIRED_ENV else cfg.api_key
        if cls.REQUIRED_ENV and not api_key:
            raise RuntimeError(f"{cls.REQUIRED_ENV[0]} not set (backend {cfg.name!r}).")

        inst = cls(model=cfg.model, base_url=merged.get("base_url", ""), port=str(merged.get("port", "")))
        inst.api_key = api_key
        inst.timeout = cfg.timeout
        inst.rate_limits = dict(cfg.rate_limits)
        inst.ctx_size = inst._resolve_ctx(cfg.ctx_size, merged.get("ctx_size", 4096))
        inst.extra = cfg.extra
        inst._post_config(cfg)
        return inst

    def _resolve_ctx(self, cfg_ctx, default) -> int:
        if cfg_ctx == "auto":
            try:
                return self._discover_ctx()
            except Exception as e:
                logger.warning(f"ctx_size discovery failed for {self.base_url}: {e}")
                return default
        return int(cfg_ctx) if cfg_ctx else default

    def _discover_ctx(self) -> int:
        raise NotImplementedError

    def _post_config(self, cfg: BackendConfig) -> None:
        """Subclass hook for model discovery, /models fetch, etc."""
        pass

    def get_model(self):
        raise NotImplementedError("Subclasses must implement get_models()")

    def get_models(self) -> list[str]:
        raise NotImplementedError("Subclasses must implement get_models()")

    def get_client(self) -> tuple[OpenAI, str]:
        raise NotImplementedError("Subclasses must implement get_client()")

    def set_base_url(self, base_url, port=None):
        #parsed = urlsplit(base_url)
        #print (f"Setting base URL to {base_url} with port {port}")
        msg_str = f"Setting base URL to {base_url}"
        if port:
            msg_str += f" with port {port}"
        logger.info(msg_str)
        parsed = urlparse(base_url)


        logger.debug(f"Parsed URL: {parsed}") # print(parsed)

        base_url =  parsed.netloc.split(":")[0] or parsed.netloc
        if port:
            parsed = parsed._replace(netloc=f"{base_url}:{self.port}")
        # parsed = parsed._replace(port=port)

        self.base_url = parsed.geturl().rstrip("/")
        logger.info (f"Set base url to {self.base_url}")
        # raise Exception("debugging")

    @property
    def is_active(self):
        return "not_implemented"

class OllamaCloudEndpoint(APIEndpoint):
    DEFAULTS = {"base_url": "https://ollama.com/api", "port": "443", "ctx_size": 32768}
    REQUIRED_ENV = ["OLLAMA_API_KEY"]

    def __init__(self, model="", base_url="", port="443", **_):
        super().__init__(model, base_url, port)

    def _post_config(self, cfg):
        self.available_models = self.get_models()
        if not self.model and self.available_models:
            self.model = self.available_models[0]

    def get_model(self):
        # risky.
        return self.model or None
    def get_models(self) -> list[str]:
        try:
            r = httpx2.get(f"{self.base_url}/models",
                           headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10)
            r.raise_for_status()
            return [m["id"] for m in r.json().get("data", []) if "id" in m]
        except Exception as e:
            logger.error(f"Failed to retrieve Ollama Cloud models: {e}")
            return []

    def get_client(self) -> tuple[OpenAI, str]:
        logger.info(f"Ollama Cloud model resolved to: {self.model}")
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model

class OpenAIEndpoint(APIEndpoint):

    def __init__(self, model: str = "", base_url: str = "http://localhost", port: str = "8080"):
        if port == "None":
            raise Exception("What the actual fuck?")
        if port is None:
            port = "8080"
        self.port = port
        super().__init__(model, base_url, self.port)
        self.api_key = "00000000"
        self.ctx_size = 32768  # Sensible default fallback;
        self.model = model
        if not base_url:
            host_ip = get_gateway_ip()
            base_url = f"http://{host_ip}:{self.port}"
        self.set_base_url(base_url.rstrip("/"), self.port)
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.available_model_data = MODEL_CATALOGS["openai"]()
        self.available_models = self.get_models()

        self.try_get_model()

    def get_client(self) -> tuple[OpenAI, str]:
        return OpenAI(base_url=f"{self.base_url}", api_key=self.api_key), self.model

    def get_model(self):
        if not self.model:
            return self.try_get_model()

    def get_models(self):
        if isinstance(self.available_model_data, dict):
            self.available_models = list(self.available_model_data.keys())
        else:
            self.available_models = self.available_model_data
        return self.available_models

    def try_get_model(self) -> str:
        self_model = self.model or ""
        try:
            response = httpx2.get(f"{self.base_url}/models", timeout=5)
            response.raise_for_status()
            models_data = response.json().get("data", [])
            self.available_models = [m.get("id") for m in models_data if "id" in m]
            self.model = next((m for m in self.available_models if m.startswith(self_model)), self.model)
            if self.model:
                return self.model
        except Exception as e:
            logger.error(f"Failed to retrieve models from {self.base_url}: {e}")
            if "No connection could be made" in str(e):
                raise Exception(f"Failed to connect to {self.base_url}")
        try:
            self.base_url = self.base_url.rstrip("/v1")
            url = self.base_url.removesuffix("/v1")  + "/api/v1/model"
            current_model = httpx2.get(url)
            if current_model:
                self.model = current_model.json().get("result", self.model)
            return self.model
        except Exception as e:
            logger.error(f"Failed to retrieve current model from {self.base_url}: {e}")
        try:
            url = self.base_url.removesuffix("/v1")  + "/models"
            models = httpx2.get(url)
            models = models.json()["models"]
            model_names = [model["name"] for model in models]
            if self.model not in model_names:
                logger.info(f"Setting default model to {models[0]['name']}")
                self.model = models[0]["model"]
        except Exception as e:
            logger.error(f"Failed to retrieve available models from {self.base_url}: {e}")

        return self.model


class KoboldCppApiendpoint(APIEndpoint):
    def __init__(self, model: str = "", base_url: str = "", port: str = "5001"):
        super().__init__(model, base_url)
        self.port = os.getenv("KOBOLD_PORT", port) or "5001"
        logger.warning("kobold: %s", self.port)
        assert self.port is not None
        if not base_url:
            host_ip = get_gateway_ip()
            self.base_url = os.getenv("KOBOLD_BASE_URL", f"http://{host_ip}:{self.port}/")
        self.set_base_url(base_url.rstrip("/"), self.port)
        # if not self.base_url.endswith("/v1"):
        #     self.base_url += "/v1"
        self.ctx_size = 8192
        self.api_key = "kobold"
        try:
            self.available_models = MODEL_CATALOGS["koboldcpp"]()
            self.model = self.get_kobold_model()
            self.ctx_size = self.get_kobold_ctx()
        except Exception as e:
            logger.error(f"Failed to get Kobold model: {e}")
            self.model = ""

    def get_kobold_ctx(self):
        # /api/extra/true_max_context_length
        current_ctx = httpx2.get(self.base_url + "/api/extra/true_max_context_length")
        return current_ctx.json()["value"]

    def get_model(self):
        self.get_kobold_model()

    def get_models(self):
        self.get_kobold_model()

    def get_kobold_model(self):
        # /api/v1/model
        current_model = httpx2.get(self.base_url + "/api/v1/model")
        # format: {"result": "<model_name>"}
        return current_model.json()["result"]

    def get_client(self) -> tuple[OpenAI, str]:
        # Return openapi compatible way for now
        return OpenAI(base_url=f"{self.base_url}", api_key=self.api_key), self.model

class LlamaApiEndpoint(APIEndpoint):
    """ TODO:
    implement wrappers maybe?
        Endpoint	Purpose
        GET /health	Liveness check: 200 when ready, 503 while loading
        POST /completion	Native completion with the full llama.cpp option set (token arrays, n_probs logprobs, id_slot pinning, per-request LoRA scales, …)
        POST /tokenize / POST /detokenize	Convert between text and tokens
        POST /apply-template	Apply the model’s chat template without running inference
        POST /infill	Fill-in-the-middle code completion from input_prefix and input_suffix
        GET /props	Server and model properties (context size, chat template, modalities)
        GET /slots	Current state of each processing slot
        GET /metrics	Prometheus metrics (requires --metrics)
        GET /lora-adapters / POST /lora-adapters	List and set LoRA adapter scales at runtime
    """
    def __init__(self, model: str = "", base_url: str = "", port="9931"):
        self.port = os.getenv("LLAMA_PORT", port or "9931")
        if not base_url:
            host_ip = get_gateway_ip()
            base_url = os.getenv("LLAMA_BASE_URL", f"http://{host_ip}:{self.port}/v1")
        super().__init__(model, base_url, self.port)

        logger.debug(f"Setting base URL to {base_url} port {self.port} vs {port}")
        self.set_base_url(base_url.rstrip("/"), self.port)
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        # if not base_url:
        #     host_ip = get_gateway_ip()
        #     self.base_url = os.getenv(
        #         "LLAMA_BASE_URL",
        #         f"http://{host_ip}:{self.port}/v1"
        # ).rstrip("/")
        if os.getenv("DEBUG", "false").lower() == "true":
            logger.info(self.base_url)
        self.api_key = "llama"
        # Can be overwritten by args
        # Futureproofs
        self.available_model_data = MODEL_CATALOGS["llamacpp"]()
        if isinstance(self.available_model_data, dict):
            self.available_models = list(self.available_model_data.keys())
        else:
            self.available_models = self.available_model_data
        # logger.info(f"Available models: {self.available_models}")
        # Empty means resolve the model from the server.
        self.model = model
        if not self.model:
            self.set_default_model()
        try:
            self.ctx_size = self.get_context_size()
        except Exception as e:
            logger.warning(f"Failed to get context size: {e}")

    @property
    def is_active(self):
        if not self.base_url:
            return False
        url = self.base_url.removesuffix("/v1") + "/slots"
        response=httpx2.get(url, timeout=10)
        response.raise_for_status()
        slots = response.json()
        for slot in slots:
            # Assume just one now tho
            if slot.get("is_processing", False):
                return True
        return False



    def get_context_size(self) -> int:
        url = self.base_url.removesuffix("/v1") + "/props"
        response = httpx2.get(url, timeout=10)
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

    def get_models(self):
        return self.get_llama_models()

    def set_default_model(self):
        models = self.get_llama_models()
        if not models:
            logger.warning("No models found from LLaMA endpoint.")
            return
        model_names = [model["name"] for model in models]
        if self.model not in model_names:
            logger.info(f"Setting default model to {models[0]['name']}")
            self.model = models[0]["model"]
        return self.model

    def get_llama_models(self):
        # /api/v1/model
        if not self.base_url:
            return []
        available_models = httpx2.get(self.base_url + "/models")
        # format: {"result": "<model_name
        return available_models.json().get("models", [])

class OllamaApiEndpoint(APIEndpoint):
    def __init__(self, model: str = "", base_url: str = "", port="11434"):
        self.port = os.getenv("OLLAMA_PORT", port or "11434")
        if not base_url:
            host_ip = get_gateway_ip()
            base_url = os.getenv(
                "OLLAMA_BASE_URL", f"http://{host_ip}:{self.port}/v1"
            )
        super().__init__(model, base_url, self.port)
        self.set_base_url(base_url.rstrip("/"), self.port)
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.api_key = "ollama"
        self.ctx_size = 8192
        self.available_models = MODEL_CATALOGS["ollama"]()
        self.model = model or self.get_model() or self.available_models[0]

    def get_client(self) -> tuple[OpenAI, str]:
        # Resolve default model at the last possible moment
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model

    def get_model(self):
        self.model = self.get_ollama_model()

    def get_models(self):
        return self.available_models

    def get_ollama_model(self):
        # /apimodel
        # current_model = httpx2.get(self.base_url + "/api/v1/model")
        for model in self.available_models:
            if self.model in model:
                return model
        return self.available_models[0]


class MistralApiEndpoint(APIEndpoint):
    def __init__(self, model: str = "", base_url: str = "", port="443"):
        super().__init__(model, base_url=base_url)
        self.base_url = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
        self.ctx_size = 32000
        self.available_models = MODEL_CATALOGS["mistral"]()
        self.model = model or self.available_models[0]
        self.port = port
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.rate_limits = {
            "tokens_per_minute": 40000,
            "requests_per_second": 1
            }
        if not self.api_key:
            raise RuntimeError("MISTRAL_API_KEY not set.")

    def get_model(self):
        return self.model

    def get_models(self) -> list[str]:
        return self.available_models

    def get_client(self) -> tuple[OpenAI, str]:
        logger.info(f"Mistral model resolved to: {self.model}")
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model

# --- AI HORDE ---
# from llm_utils import Message

# class AiHordeClientChat:

#     def __init__(self, base_url, api_key):
#         self.base_url = base_url
#         self.api_key = api_key
#         self._client = None

#     @property
#     def completions(self):
#         # TODO: There is an asyncclient but the endpoint is naturally async...
#         self._client = self._client or httpx2.Client(base_url=self.base_url)
#         return self

#     def get_message(self, messages):
#         message_template = {
#             "role": "user",
#             "content": {},
#             "name": "string",
#             "tool_calls": [
#                 {
#                 "id": "string",
#                 "type": "function",
#                 "function": {
#                     "name": "string",
#                     "arguments": "string"
#                 }
#                 }
#             ],
#             "tool_call_id":
#         }
#         return [message_template.copy().update(
#             {"role": m["role"],
#              "content": m["content"],
#              "tool_calls": m.get("tool_calls",[])}) for m in messages]


#     # Synchronous wrapper
#     def create(self, model, messages, tools=None, tool_choice=None):
#         self.messages=messages
#         self.tools=tools
#         self.tool_choice = tool_choice
#         if not self._client or not isinstance(self._client, httpx2.Client):
#             raise APIError("No client set in ApiHorde")

#         request = self._client.post(
#             f"{self.base_url}/generate/chat/async",
#             content="",
#             data={

#                 "model": model,
#                 "messages": messages,
#             },
#             headers={
#                 "apikey": self.api_key

#             }
#         )



# TODO: Should we inherit OpenAI?

# class AiHordeClient:
#     # Implements openai-like interface, for now.
#     def __init__(self, base_url, api_key):
#         self.chat = AiHordeClientChat(base_url, api_key)


class AIHordeEndpoint(APIEndpoint):
    """AI Horde through its OpenAI-compatible chat front."""
    def __init__(self, model: str = "", base_url: str = "", port="443"):
        super().__init__(model, base_url=base_url)

        self.base_url = os.getenv(
            "AIHORDE_BASE_URL",
            "https://oai.aihorde.net/v1"
        )
        self.port = port
        self.api_key = os.getenv("AIHORDE_API_KEY", "")

        if not self.api_key:
            raise RuntimeError("AIHORDE_API_KEY not set.")

        self.ctx_size = 8192

        self.available_models = self.get_models()

        if model:
            self.model = model
        elif self.available_models:
            self.model = self.available_models[0]
        else:
            self.model = ""

    #...should I deprecate this or make it return data from specific model? TODO apichange.
    def get_model(self, model=None):
        return self.model

    def get_models(self) -> list[str]:
        try:
            response = httpx2.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            response.raise_for_status()

            data = response.json().get("data", [])
            return [m["id"] for m in data if "id" in m]

        except Exception as e:
            logger.error(f"Failed to retrieve AI Horde models: {e}")
            return []

    def get_client(self) -> tuple[OpenAI, str]:
        logger.info(f"AI Horde model resolved to: {self.model}")

        return (
            OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            ),
            self.model,
        )


class OpenRouterEndpoint(APIEndpoint):
    """OpenRouter endpoint for accessing multiple LLM providers."""
    def __init__(self, model: str = "", base_url: str = "", port="443"):
        super().__init__(model, base_url=base_url)
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.ctx_size = 128000  # OpenRouter supports large context models
        self.available_models = MODEL_CATALOGS["openrouter"]()
        self.model = model or (self.available_models[0] if self.available_models else "")
        self.port = port
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.rate_limits = {
            "tokens_per_minute": 100000,
            "requests_per_second": 10
        }
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set.")

    def get_model(self):
        # risky.
        return self.model or None

    def get_models(self) -> list[str]:
        return self.available_models

    def get_client(self) -> tuple[OpenAI, str]:
        logger.info(f"OpenRouter model resolved to: {self.model}")
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model


# api_endpoint.py  (bottom of file)
DRIVERS: Dict[str, Type[APIEndpoint]] = {
    "ollama":        OllamaApiEndpoint,
    "ollama_cloud":  OllamaCloudEndpoint,
    "mistral":       MistralApiEndpoint,
    "koboldcpp":     KoboldCppApiendpoint,
    "llamacpp":      LlamaApiEndpoint,
    "openai":        OpenAIEndpoint,
    "groq":          OpenAIEndpoint,
    "aihorde":       AIHordeEndpoint,
    "openrouter":    OpenRouterEndpoint,
}

def build_endpoint(cfg: BackendConfig) -> APIEndpoint:
    cls = DRIVERS.get(cfg.type)
    if not cls:
        raise ValueError(f"Unknown backend type {cfg.type!r} (name={cfg.name})")
    return cls.from_config(cfg)

def build_all(settings: ProxyConfig) -> Dict[str, APIEndpoint]:
    return {b.name: build_endpoint(b) for b in settings.backends}

settings = ProxyConfig.from_file(Path.cwd() / "backend.yaml")
endpoints = build_all(settings)

if __name__ == "__main__":
    for name, ep in endpoints.items():
        if ep.available_models:
            print("-"*60)
            print(f"## {name}")
            for m in ep.available_models:
                print(m)
            print(ep.get_model())


BACKEND_MAP = DRIVERS
