# endpoint_config.py
from __future__ import annotations
import os, re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union, Optional
import yaml
from dataclasses import replace
import dotenv

dotenv.load_dotenv()

# DIE IN FIRE if dotenv not available.

_ENV = re.compile(r"\$\{([^}]+)\}")

def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


# endpoint_config.py
@dataclass
class BackendConfig:
    name: str
    type: str
    base_url: Optional[str] = None       # None = not supplied
    port: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    ctx_size: Union[int, str, None] = None
    timeout: int = 60
    rate_limits: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "BackendConfig":
        raw = _expand(raw)
        def norm(v):                                       # treat "" / "None" as missing
            return None if v in (None, "", "None", "none") else v
        return cls(
            name=raw["name"],
            type=raw["type"],
            base_url=norm(raw.get("base_url")),
            port=str(raw["port"]) if raw.get("port") not in (None, "", "None") else None,
            api_key=norm(raw.get("api_key")),
            model=norm(raw.get("model")),
            ctx_size=norm(raw.get("ctx_size")),
            timeout=int(raw.get("timeout", 60)),
            rate_limits=raw.get("rate_limits") or {},
            extra={k: v for k, v in raw.items()
                   if k not in cls.__dataclass_fields__},
        )

    def with_overrides(self, **kw) -> "BackendConfig":
        """Override only fields explicitly supplied; leave the rest None."""
        out = {}
        for k, v in kw.items():
            if v is None or v == "" or v == "None":
                continue
            out[k] = str(v) if k == "port" else v
        return replace(self, **out)


    @classmethod
    def from_cli(cls, type_: str, *, model="", base_url="", port=None, **extra) -> "BackendConfig":
        """Build a one-off BackendConfig for CLI/TUI overrides."""
        return BackendConfig(
            name=f"cli-{type_}", type=type_, model=model if model else cls.model,
            base_url=base_url or cls.base_url, port=str(port) if port is not None else cls.port,
            extra=extra,
        )


@dataclass
class ProxyConfig:
    host: str = "127.0.0.1"
    port: int = 8041
    log_level: str = "info"
    backends: List[BackendConfig] = field(default_factory=list)
    routes: List[Dict[str, Any]] = field(default_factory=list)
    default: Dict[str, Any] = field(default_factory=dict)
    memory: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> "ProxyConfig":
        with open(path) as f:
            return cls.from_dict(yaml.safe_load(f) or {})

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ProxyConfig":
        raw = _expand(raw)
        return cls(
            host=raw.get("host", "127.0.0.1"),
            port=int(raw.get("port", 8041)),
            log_level=raw.get("log_level", "info"),
            backends=[BackendConfig.from_dict(b) for b in raw.get("backends", [])],
            routes=raw.get("routes", []),
            default=raw.get("default", {}),
            memory=raw.get("memory", {}),
        )

    def backend(self, name: str) -> BackendConfig:
        for b in self.backends:
            if b.name == name:
                return b
        raise KeyError(f"No backend named {name!r}")