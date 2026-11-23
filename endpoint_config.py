# endpoint_config.py
from __future__ import annotations
import os, re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union
import yaml

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

@dataclass
class BackendConfig:
    name: str
    type: str                                 # driver key
    base_url: str = ""
    port: str = ""
    api_key: str = ""
    model: str = ""
    ctx_size: Union[int, str] = 4096          # int or "auto"
    timeout: int = 60
    rate_limits: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)   # driver-specific overflow

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "BackendConfig":
        raw = _expand(raw)
        known = set(cls.__dataclass_fields__)
        kwargs = {k: v for k, v in raw.items() if k in known and k != "extra"}
        extra = {k: v for k, v in raw.items() if k not in known}
        return cls(extra=extra, **kwargs)

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