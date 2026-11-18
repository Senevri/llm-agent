import os
from pathlib import Path
from typing import Dict, Optional, Type
from urllib.parse import urlparse, urlsplit

import httpx2 as requests
import yaml
from custom_logger import setup_logging
from dotenv import load_dotenv
from get_ip import get_gateway_ip
from llm_utils import (UsageTracker, discover_candidate_dir,
                       discover_context_window)
from api_endpoint import APIEndpoint, BACKEND_MAP
from openai import OpenAI

AGENT_DIR = os.getenv("AGENT_DIR", "/agent")
if not Path(AGENT_DIR).exists():
    AGENT_DIR = discover_candidate_dir(Path(__file__).resolve().parent, Path("agent")) / "agent"

load_dotenv(f"{AGENT_DIR}/.env")

if not Path("/workspace").exists():
    LOG_DIR = Path.cwd() / "logs/"
else:
    LOG_DIR = os.getenv("LOG_DIR", "/workspace/logs/")

logger = setup_logging("Backend", level="INFO", log_dir=Path(LOG_DIR))




class LLMBackend:
    def __init__(self, backend: str = "mistral", config_file: str = "endpoints.yaml", defer_init=False):
        self.backend = backend
        self.endpoints = self.load_endpoints(config_file)
        self.usage = UsageTracker()
        self.model = os.getenv("AGENT_MODEL", "")
        logger.info(f"Backend: {backend}, Model: {self.model or '(default)'}")
        self.backends = BACKEND_MAP.keys()
        if not defer_init:
            self.endpoint: Optional[APIEndpoint] = BACKEND_MAP[self.backend](model=self.model)
            assert self.endpoint
            self.port: Optional[int] = self.endpoint.port
            self.context_limit = self.endpoint.ctx_size
            if self.endpoint.rate_limits:
                logger.debug(f"setting rate limits: {self.endpoint.rate_limits}")
                self.usage.set_usage_limits(
                    **self.endpoint.rate_limits
                    )
            self.base_url=self.endpoint.base_url
            self.endpoint.api_key = os.getenv(f"{self.backend}_API_KEY", "00000000")
        else:
            self.endpoint = None
            self.port = None
            self.context_limit = -1
            self.base_url = "http://localhost:8080"
        self.logger = logger
        self.client = None

    def set_model(self, model: str):
        self.model = model or self.model
        return self.model

    def find_model(self, model: str):
        for m in self.available_models:
            logger.debug(f"Comparing {model} to {m}")
            model = model.lower()
            _m = m.lower()
            if str(model) == str(_m):
                return m
            if str(_m).startswith(model):
                return m
            if model in str(_m):
                return m
        return None

    @property
    def available_models(self) -> list[str]:
        try:
            return self.endpoint.available_models
        except:
            return []

    def load_endpoints(self, config_file: str) -> Dict:
        """_summary_

        # format:
        ```yaml
        endpoints:
            openai:
                base_url: https://api.openai.com/v1
                chat_models:
                    gpt-3.5-turbo: chat, tools
                    gpt-4: chat, coding <other tags>
        ```
        """
        Path(config_file).touch(exist_ok=True)
        return yaml.safe_load(open(config_file, encoding="utf-8"))

    def _get_endpoint(self):
        endpoint_cls = BACKEND_MAP.get(self.backend)
        if not endpoint_cls:
            raise ValueError(f"Unsupported backend: {self.backend}")

        # The constructor now receives the correct, final values immediately
        self.endpoint = endpoint_cls(
            model=self.model,
            base_url=self.base_url,
            port=self.port
        )
        self.usage.set_usage_limits(**self.endpoint.rate_limits)
        return self.endpoint

    def update_context_limit(self, context_limit: int):

        self.context_limit = int(context_limit)
        self.usage.context_limit = context_limit
        logger.info(f"Context window set to: {context_limit}")


    def get_client(self) -> tuple[OpenAI, str]:
        """Initializes the correct endpoint, discovers context, and returns the client."""

        if not self.endpoint:
            raise ValueError(f"Unsupported backend: {self.backend}")
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
        self.client = client

        return client, resolved_model
        # return endpoint.get_client()


if __name__ == "__main__":
    from argparse import ArgumentParser
    from pprint import pprint


    defaultbackend = os.getenv("AGENT_BACKEND", "llamacpp")
    parser = ArgumentParser()
    parser.add_argument("--backend", type=str, default=defaultbackend, help="LLM backend to use (ollama, mistral, koboldcpp, llamacpp)")
    parser.add_argument("--model", type=str, default="", help="Model name to use (if applicable)")
    parser.add_argument("--port", type=int, default=None, help="Port for the backend service (if applicable)")
    args=parser.parse_args()

    # backend="mistral"
    # model="ministral-14b-latest"

    llm_backend = LLMBackend(backend=args.backend, defer_init=True)
    llm_backend.port = args.port or llm_backend.port


    if args.model:
        llm_backend.set_model(args.model)

    llm_backend._get_endpoint()
    if not llm_backend.endpoint:
        raise ValueError(f"Unsupported backend: {llm_backend.backend}")
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
    print(
        f"Usage: Rate limits: TPM: {llm_backend.usage.tokens_per_minute} RPS: {llm_backend.usage.requests_per_second} "
        f"Used: {llm_backend.usage.prompt_tokens} in window: {llm_backend.usage.tokens_used_in_window} tokens")
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