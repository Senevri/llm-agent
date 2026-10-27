from dataclasses import dataclass, field
import os
import requests
from typing import Optional

@dataclass
class UsageTracker:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    last_prompt_tokens: int = 0
    context_limit: int = 4096          # the *served* window, not the model max
    per_turn: list = field(default_factory=list)

    def record(self, usage, turn: int | None = None) -> None:
        if usage is None:
            return
        p = getattr(usage, "prompt_tokens", 0) or 0
        c = getattr(usage, "completion_tokens", 0) or 0
        # Ollama cache-hit quirk: p == 0 means "cached", not "empty".
        if p == 0 and self.last_prompt_tokens:
            p = self.last_prompt_tokens      # best available estimate
        self.prompt_tokens += p
        self.completion_tokens += c
        self.calls += 1
        self.last_prompt_tokens = p
        self.per_turn.append({"turn": turn, "prompt": p, "completion": c})

    @property
    def context_pct(self) -> float:
        if not self.context_limit:
            return 0.0
        return 100.0 * self.last_prompt_tokens / self.context_limit

    def summary(self) -> str:
        return (
            f"calls={self.calls} "
            f"in={self.prompt_tokens} out={self.completion_tokens} "
            f"ctx={self.last_prompt_tokens}/{self.context_limit} "
            f"({self.context_pct:.0f}%)"
        )



def discover_context_window(base_url: str, model: str, default: int = 4096, backend="ollama") -> int:
    """Served context window from Ollama's native API. Falls back to
    /api/show (model max) then to the server default. base_url is the
    OpenAI-compat URL, e.g. http://host:11434/v1; we strip /v1."""
    if backend == "ollama":
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]

        # 1. Live served value — the one that actually matters.
        try:
            r = requests.get(f"{root}/api/ps", timeout=5)
            r.raise_for_status()
            for m in r.json().get("models", []):
                if m.get("name") == model or m.get("model") == model:
                    return int(m["context_length"])
        except Exception:
            pass

        # 2. Model max, even if not loaded. Scan arch-prefixed keys.
        try:
            r = requests.post(f"{root}/api/show", json={"model": model}, timeout=5)
            r.raise_for_status()
            info = r.json().get("model_info", {})
            for k, v in info.items():
                if k.endswith(".context_length") and isinstance(v, int):
                    return v
        except Exception:
            pass

        # 3. Server default. 4096 on recent builds, 2048 on older ones.
        return default
    else:
        return discover_openai_context_window(base_url, model, default)


def discover_openai_context_window(
    base_url: str,
    model: str,
    default: int = 32768,
    api_key: Optional[str] = None
) -> int:
    """
    Discovers the context window for a given model via the OpenAI-compatible /v1/models endpoint.
    Works natively with Mistral, OpenAI, and other providers that expose `context_window` in their model list.

    :param base_url: The OpenAI-compat URL (e.g., "https://api.mistral.ai/v1" or "http://localhost:11434/v1")
    :param model: The model name (e.g., "mistral-small-latest")
    :param default: Fallback context window if the API call fails or the field is missing.
    :param api_key: Optional API key. Falls back to MISTRAL_API_KEY or OPENAI_API_KEY env vars.
    """
    # Ensure base_url is clean and points to the /v1 endpoint
    root = base_url.rstrip("/")
    if not root.endswith("/v1"):
        root = f"{root}/v1"

    # Resolve API key from arguments or environment
    resolved_api_key = api_key or os.getenv("MISTRAL_API_KEY") or os.getenv("OPENAI_API_KEY")

    headers = {}
    if resolved_api_key:
        headers["Authorization"] = f"Bearer {resolved_api_key}"

    try:
        # Query the standard OpenAI-compatible model list endpoint
        r = requests.get(f"{root}/models", headers=headers, timeout=5)
        r.raise_for_status()

        models_data = r.json().get("data", [])
        for m in models_data:
            # OpenAI/Mistral use "id" for the model identifier
            if m.get("id") == model:
                # Mistral explicitly includes "context_window" in this response
                if "context_window" in m:
                    return int(m["context_window"])

                # Fallback for other providers that might use a different key name
                if "max_tokens" in m:
                    return int(m["max_tokens"])

            # Loose match fallback: e.g., user passes "mistral-small", API returns "mistral-small-latest"
            elif model in m.get("id", ""):
                if "context_window" in m:
                    return int(m["context_window"])

    except Exception:
        # Silently fail and fall back to default (network error, bad key, or endpoint doesn't support it)
        pass

    return default