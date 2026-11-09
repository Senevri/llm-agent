import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, Type

import httpx2
from openai import OpenAI

SCRIPT_DIR = Path(__file__).resolve().parent.parent

if SCRIPT_DIR not in sys.path:
    sys.path.append(str(SCRIPT_DIR))

from custom_logger import setup_logging
from model_catalog import MODEL_CATALOGS
from get_ip import get_gateway_ip

logger = setup_logging(__name__) # Could use unifiedagent

class APIEndpoint:
    """Base class for LLM API endpoints."""
    def __init__(self, model: str = "", base_url: str = "", port = "443"):
        self.model = model
        self.base_url = base_url
        self.port = port
        self.api_key = ""
        self.available_models = []
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
        logger.debug(f"Parsed URL: {parsed}") # print(parsed)

        base_url =  parsed.netloc.split(":")[0] or parsed.netloc
        parsed = parsed._replace(netloc=f"{base_url}:{port}")
        # parsed = parsed._replace(port=port)

        self.base_url = parsed.geturl()
        logger.info (f"Set base url to {self.base_url}")
        # raise Exception("debugging")

class OpenAIEndpoint(APIEndpoint):

    def __init__(self, model: str = "", base_url: str = "http://localhost", port: int = 8080):

        super().__init__(model, base_url)
        self.port = port
        self.api_key = "00000000"
        self.ctx_size = 32768  # Sensible default fallback;
        self.model = model
        self.set_base_url(base_url, port)
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.available_models = MODEL_CATALOGS["openai"]()
        self.try_get_model()

    def get_client(self) -> tuple[OpenAI, str]:
        return OpenAI(base_url=f"{self.base_url}/v1", api_key=self.api_key), self.model

    def get_model(self):
        if not self.model:
            return self.try_get_model()

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
        try:
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
        self.port = os.getenv("KOBOLD_PORT", port)
        if not base_url:
            host_ip = get_gateway_ip()
            self.base_url = os.getenv("KOBOLD_BASE_URL", f"http://{host_ip}:{self.port}/")
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

    def get_models(self):
        self.get_kobold_model()

    def get_kobold_model(self):
        # /api/v1/model
        current_model = httpx2.get(self.base_url + "/api/v1/model")
        # format: {"result": "<model_name>"}
        return current_model.json()["result"]

    def get_client(self) -> tuple[OpenAI, str]:
        # Return openapi compatible way for now
        return OpenAI(base_url=f"{self.base_url}/v1", api_key=self.api_key), self.model

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
        super().__init__(model, base_url)
        self.port = os.getenv("LLAMA_PORT", port)
        if not base_url:
            host_ip = get_gateway_ip()
            self.base_url = os.getenv(
                "LLAMA_BASE_URL",
                f"http://{host_ip}:{self.port}/v1"
        ).rstrip("/")
        if os.getenv("DEBUG", "false").lower() == "true":
            logger.info(self.base_url)
        self.api_key = "llama"
        # Can be overwritten by args
        self.ctx_size = 32768
        self.available_models = MODEL_CATALOGS["openai"]()
        # Empty means resolve the model from the server.
        self.model = model
        if not self.model:
            self.set_default_model()


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
        super().__init__(model, base_url)
        self.port = os.getenv("OLLAMA_PORT", port)

        if not base_url:
            host_ip = get_gateway_ip()
            self.base_url = os.getenv("OLLAMA_BASE_URL", f"http://{host_ip}:{self.port}/v1")
        self.api_key = "ollama"
        self.ctx_size = 8192  # Ollama default, but will be overwritten by discovery
        self.available_models = MODEL_CATALOGS["ollama"]()
        self.model = self.model or self.available_models[0]

    def get_client(self) -> tuple[OpenAI, str]:
        # Resolve default model at the last possible moment
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model

    def get_model(self):
        self.model = self.get_ollama_model()

    def get_ollama_model(self):
        # /apimodel
        current_model = httpx2.get(self.base_url + "/api/v1/model")
        # format: {"result": "<model_name>"}
        return current_model.json()["result"]


class MistralApiEndpoint(APIEndpoint):
    def __init__(self, model: str = "", base_url: str = "", port=None):
        super().__init__(model, base_url=base_url)
        self.base_url = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
        self.ctx_size = 32000
        self.available_models = MODEL_CATALOGS["mistral"]()
        self.model = model or self.available_models[0]
        self.port = None
        self.api_key = os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise RuntimeError("MISTRAL_API_KEY not set.")

    def get_models(self) -> list[str]:
        return self.available_models

    def get_client(self) -> tuple[OpenAI, str]:
        logger.info(f"Mistral model resolved to: {self.model}")
        return OpenAI(base_url=self.base_url, api_key=self.api_key), self.model


BACKEND_MAP: Dict[str, Type[APIEndpoint]] = {
            "ollama": OllamaApiEndpoint,
            "mistral": MistralApiEndpoint,
            "koboldcpp": KoboldCppApiendpoint,
            "llamacpp": LlamaApiEndpoint,
            "openai": OpenAIEndpoint
        }
