from dataclasses import dataclass, field
import re
import os
import httpx2
from typing import Optional, Iterable, Dict, Any

import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import tiktoken
    encoding = tiktoken.get_encoding("cl100k_base") # or your model's encoding
    def estimate_tokens(messages: list) -> int:
        return sum(len(encoding.encode(str(m))) for m in messages)
except ImportError:
    logger.warning("Could not import tiktoken. Using len(str(m)) as a fallback.")
    def estimate_tokens(messages: list) -> int:
        return sum(size_bytes(m) for m in messages) // 4

def _role(m: Any) -> str:
    if isinstance(m, dict):
        return str(m.get("role", ""))
    return str(getattr(m, "role", ""))


def normalize_messages( messages, provider):
    normalized = []

    for message in messages:
        msg = dict(message)

        if provider == "mistral":
            msg.pop("reasoning_content", None)

        normalized.append(msg)

    return normalized


def discover_candidate_dir(start: Path, test: Path):
    candidate_dir = start
    for i in range(0,4):
        if (candidate_dir / test).is_dir():
            return candidate_dir
        candidate_dir = candidate_dir.parent
    return candidate_dir


@dataclass
class UsageTracker:
    prompt_tokens: int = 0
    prompt_estimated: bool = False
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
            p = self.last_prompt_tokens
            self.prompt_estimated = True
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

    @property
    def remaining_tokens(self) -> int:
        return self.context_limit - self.last_prompt_tokens

    def summary(self) -> str:
        return (
            f"calls={self.calls} "
            f"in={self.prompt_tokens} out={self.completion_tokens} "
            f'{"[est.] " if self.prompt_estimated else ""}'
            f"ctx={self.last_prompt_tokens}/{self.context_limit} "
            f"({self.context_pct:.0f}%)"

        )

    def inspect_context(self, messages, tools=None):
        return {
            "message_count": len(messages),
            "role_counts": {
                role: sum(1 for m in messages if m.get("role") == role)
                for role in {m.get("role") for m in messages}
            },
            "content_chars": sum(
                len(str(m.get("content") or ""))
                for m in messages
            ),
            "tool_count": len(tools or []),
        }

def robust_json_extract(text: str) -> Optional[Dict[str, Any]]:
        if not isinstance(text, str):
            return None

        # Primary method: Find the outermost braces. This handles nested JSON perfectly.
        start = text.find("{")
        end = text.rfind("}")

        if start != -1 and end != -1 and end > start:
            json_str = text[start:end + 1]
        else:
            # Fallback: Try to strip markdown fences if no braces found (shouldn't happen)
            pattern = r"```(?:json)?\s*(\{.*\})\s*```" # Note: greedy .* instead of .*?
            match = re.search(pattern, text, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                return None

        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                return parsed
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode failed on extracted string: {e}\nString snippet: {json_str[:200]}")
            return balanced_braces_extract(text)

def balanced_braces_extract(text: str) -> Optional[Dict[str, Any]]:
    start = text.find("{")
    if start == -1:
        return None
    count = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            count += 1
        elif text[i] == "}":
            count -= 1
        if count == 0:
            try:
                parsed = json.loads(text[start:i + 1])
                if isinstance(parsed, dict):
                    return parsed
                return None
            except json.JSONDecodeError:
                return None
    return None


def size_bytes(value):
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, dict):
        return sum(size_bytes(k) + size_bytes(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return sum(size_bytes(item) for item in value)
    return len(str(value).encode("utf-8"))


def discover_context_window(base_url: str, model: str, default: int = 4096, backend="ollama") -> int:
    """Served context window from Ollama's native API. Falls back to
    /api/show (model max) then to the server default. base_url is the
    OpenAI-compat URL, e.g. http://host:11434/v1; we strip /v1."""
    if backend == "ollama":
        return discover_ollama_context_window(base_url, model, default)
    elif backend == "openai":
        return discover_openai_context_window(base_url, model, default)
    elif backend == "mistral":
        return discover_mistral_context_window(base_url, model, default)
    elif backend in ["openai", "koboldcpp", "llamacpp"]:
        return discover_llama_context_window(base_url, model, default)

def discover_ollama_context_window(base_url, model, default=4096):
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root.removesuffix("/v1")

    # 1. Live served value — the one that actually matters.
    try:
        r = httpx2.get(f"{root}/api/ps", timeout=5)
        r.raise_for_status()
        for m in r.json().get("models", []):
            if m.get("name") == model or m.get("model") == model:
                return int(m["context_length"])
    except Exception:
        pass

    # 2. Model max, even if not loaded. Scan arch-prefixed keys.
    try:
        r = httpx2.post(f"{root}/api/show", json={"model": model}, timeout=5)
        r.raise_for_status()
        info = r.json().get("model_info", {})
        for k, v in info.items():
            if k.endswith(".context_length") and isinstance(v, int):
                return v
    except Exception:
        pass

    # 3. Server default. 4096 on recent builds, 2048 on older ones.
    return default



def discover_llama_context_window(base_url, model, default=4096):
    # NOTE: also  curl -s localhost:5001/props | jq -r .default_generation_settings.n_ctx
    assert base_url.startswith("http"), "base_url must be a full URL, e.g. http://localhost:5001/v1"
    url = base_url.removesuffix("/v1") + "/props"
    try:
        response = httpx2.get(url, timeout=10)
        response.raise_for_status()
        props = response.json()
        ctx_size = props["default_generation_settings"]["n_ctx"]
    except Exception as e:
        logger.error(f"Failed to retrieve context size from {base_url}: {e}")
        ctx_size = None
    if __name__ == "__main__":
        logger.info("LLaMA context window size: %s", ctx_size)
    return ctx_size or default


def discover_mistral_context_window(base_url, model, default=4096):
    # todo: not implemented
    return discover_openai_context_window(base_url, model, default)

def get_openai_models(base_url, api_key):
    root = base_url.rstrip("/")
    if not root.endswith("/v1"):
        root = f"{root}/v1"

    # Resolve API key from arguments or environment
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")

    headers = {}
    if resolved_api_key:
        headers["Authorization"] = f"Bearer {resolved_api_key}"
    try:
        # Query the standard OpenAI-compatible model list endpoint
        r = httpx2.get(f"{root}/models", headers=headers, timeout=5)
        r.raise_for_status()

        return r.json().get("data", [])
    except Exception:
        # Silently fail and fall back to default (network error, bad key, or endpoint doesn't support it)
        pass

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
    models_data = get_openai_models(base_url, api_key)
    if not models_data:
        return default

    contex_window_keys = ["context_window", "n_ctx", "max_tokens"]
    try:
        for m in models_data:
            # OpenAI/Mistral use "id" for the model identifier
            if m.get("id") == model:
                for i in contex_window_keys:
                    if i in m:
                        return int(m[i])

            elif model in m.get("id", ""):
                for i in contex_window_keys:
                    if i in m:
                        return int(m[i])

    except Exception:
        # Silently fail and fall back to default (network error, bad key, or endpoint doesn't support it)
        pass

    return default

import json
try:
    from jsonschema import Draft202012Validator

    def validate_llm_json(response: str, schema: dict): # type: ignore
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            return False, None, [f"Invalid JSON syntax: {e}"]

        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(data))

        if errors:
            messages = [
                f"{'.'.join(map(str, e.absolute_path))}: {e.message}"
                for e in errors
            ]
            return False, data, messages

        return True, data, []

except ImportError:
    logger.warning("Failed to import jsonschema. Some features may not work.")
    def validate_llm_json(response: str, schema: dict):
        return True, None, []

if __name__ == "__main__":
    # Example usage of discover_context_window for different backends

    print("Ollama context window:", discover_context_window("http://localhost:11434/v1", "mistral-small-latest", backend="ollama"))
    #print("OpenAI context window:", discover_context_window("https://api.openai.com/v1", "gpt-4", backend="openai"))
    print("OpenAI context window:", discover_context_window("https://localhost:8080/v1", "gpt-4", backend="openai"))
    print("Mistral context window:", discover_context_window("https://api.mistral.ai/v1", "mistral-small-latest", backend="mistral"))
    print("LLaMA context window:", discover_context_window("http://localhost:5001/v1", "llama-2-7b-chat", backend="llamacpp"))
    print("OpenAI Models:", get_openai_models("http://localhost:8080/v1", "00000000"))