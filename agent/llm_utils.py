from dataclasses import dataclass, field
import requests
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



def discover_context_window(base_url: str, model: str, default: int = 4096) -> int:
    """Served context window from Ollama's native API. Falls back to
    /api/show (model max) then to the server default. base_url is the
    OpenAI-compat URL, e.g. http://host:11434/v1; we strip /v1."""
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