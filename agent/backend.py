import os
import sys
from pathlib import Path
from typing import Dict, Optional, Type, Any
from urllib.parse import urlparse, urlsplit

import httpx2 as requests
import yaml
from custom_logger import setup_logging
from dotenv import load_dotenv
from get_ip import get_gateway_ip
from llm_utils import (UsageTracker, discover_candidate_dir,
                       discover_context_window)
from api_endpoint import APIEndpoint, BACKEND_MAP, build_endpoint, ProxyConfig, BackendConfig, DRIVERS

from openai import OpenAI

SOURCE_PATH = Path(__file__).parent.resolve()
if SOURCE_PATH not in sys.path:
    sys.path.insert(0, str(SOURCE_PATH))

AGENT_DIR = os.getenv("AGENT_DIR", "/agent")
if not Path(AGENT_DIR).exists():
    AGENT_DIR = discover_candidate_dir(Path(__file__).resolve().parent, Path("agent")) / "agent"

load_dotenv(f"{AGENT_DIR}/.env")

if not Path("/workspace").exists():
    LOG_DIR = Path.cwd() / "logs/"
else:
    LOG_DIR = os.getenv("LOG_DIR", "/workspace/logs/")

logger = setup_logging("Backend", level="INFO", log_dir=Path(LOG_DIR))


def find_yaml_path(config_file):
    path = SOURCE_PATH / config_file
    if path.exists():
        return path
    return [p for p in Path(SOURCE_PATH.parent).rglob(config_file)][0]


class LLMBackend:
    def __init__(self, backend: str = "mistral", config_file: str = "backend.yaml", model: str = "", defer_init: bool = False, port: Optional[int] = None):
        self.backend = backend
        self._settings: Optional[ProxyConfig] = None
        self._yaml_path = find_yaml_path(config_file)
        assert self._yaml_path.exists()

        self.endpoint: Optional[APIEndpoint] = None
        self.usage = UsageTracker()
        self._last_overrides: Dict[str, Any] = {}

        # Only treat env/args as overrides if explicitly set (keep None otherwise!)
        self.port: Optional[str] = str(port) if port is not None else None
        self.model: Optional[str] = os.getenv("AGENT_MODEL") or model or None
        self.base_url: Optional[str] = None
        self.context_limit: int = -1
        self.client = None
        self.logger = logger

        if not defer_init:
            self.switch(backend, port=self.port, model=self.model)

    def _get_endpoint(self):
        # Only pass non-None overrides so YAML isn't clobbered by "http://localhost"
        return self.switch(
            self.backend,
            model=self.model,
            base_url=self.base_url,
            port=self.port,
        )

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


    @property
    def settings(self) -> ProxyConfig:
        """Lazy-load YAML once, cache. Call .reload() to refresh."""
        if self._settings is None:
            if not self._yaml_path.exists():
                self._settings = ProxyConfig(backends=[], routes=[], default={})
            else:
                self._settings = ProxyConfig.from_file(self._yaml_path)
        return self._settings

    def reload(self) -> None:
        """Force YAML reload on next access."""
        self._settings = None

    def switch(self, backend: str, **overrides) -> APIEndpoint:
        """
        TUI entry point. Rebuilds the endpoint from YAML defaults + overrides.

        /backend ollama                       -> switch("ollama")
        /backend ollama port=1234             -> switch("ollama", port="1234")
        /backend ollama base_url="http://x"   -> switch("ollama", base_url="http://x")
        /backend ollama model=qwen2:7b        -> switch("ollama", model="qwen2:7b")
        /backend llamacpp port=1234 base_url=x -> switch("llamacpp", port="1234", base_url="x")
        """
        self.backend = backend
        self._last_overrides = dict(overrides)

        cfg = self._resolve_config(backend, overrides)
        self.endpoint = build_endpoint(cfg)

        # sync LLMBackend's view
        self.port = self.endpoint.port
        self.base_url = self.endpoint.base_url
        self.model = self.endpoint.model or self.model
        self.context_limit = self.endpoint.ctx_size
        if self.endpoint.rate_limits:
            self.usage.set_usage_limits(**self.endpoint.rate_limits)

        # invalidate cached client — caller must call get_client() again
        self.client = None
        return self.endpoint


    def _resolve_config(self, backend: str, overrides: dict) -> BackendConfig:
        """
        Resolve a BackendConfig by:
          1. Try YAML entry by name
          2. Try YAML entry by type (if exactly one match)
          3. Fall back to driver DEFAULTS + overrides only
        Then apply overrides on top.
        """
        # 1. by name
        for b in self.settings.backends:
            if b.name == backend:
                return b.with_overrides(**overrides)

        # 2. by type (driver key)
        matches = [b for b in self.settings.backends if b.type == backend]
        if len(matches) == 1:
            return matches[0].with_overrides(**overrides)
        if len(matches) > 1:
            names = [b.name for b in matches]
            raise ValueError(
                f"Backend {backend!r} is ambiguous — multiple YAML entries "
                f"of type {backend!r}: {names}. Use the name instead."
            )

        # 3. not in YAML — build from driver DEFAULTS + overrides only
        if backend not in DRIVERS:
            raise ValueError(
                f"Unknown backend {backend!r}. "
                f"Known drivers: {list(DRIVERS.keys())}"
            )
        return BackendConfig(
            name=f"cli-{backend}",
            type=backend,
            model=overrides.get("model", ""),
            base_url=overrides.get("base_url", ""),
            port=str(overrides.get("port", )) if overrides.get("port") else "",
            api_key=overrides.get("api_key", ""),
        )

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
            self.usage.context_limit = self.endpoint._discover_ctx()
            if not self.usage.context_limit:
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
    parser.add_argument("--test", action="store_true")
    args=parser.parse_args()

    # backend="mistral"
    # model="ministral-14b-latest"

    if not args.test:
        llm_backends = [args.backend]
    else:
        llm_backends =  [str(k) for k in DRIVERS.keys()]

    for backend in llm_backends:
        logger.info(f"---backend: {backend}")
        try:
            llm_backend = LLMBackend(backend=backend, defer_init=True, port=args.port)
            llm_backend.port = args.port or llm_backend.port
            if args.model:
                llm_backend.set_model(args.model)
            llm_backend._get_endpoint()

        except Exception as e:
            print (e)
            continue


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
        #exit(0)
        continue
        # msg = "What is Mistral AI?"
        msg = "Tell me about yourself concisely in tweet length."

        response = client.chat.completions.create(
            model=resolved_model,
            messages=[{"role": "user", "content": msg}],
            tools=[],
            tool_choice="auto"
        )
        pprint(response)