"""Rich TUI chat interface for LLM APIs with multi-phase processing.

Overview
--------
This module implements a small but complete chat application that talks to an
OpenAI-compatible LLM endpoint (Ollama by default).  Unlike a plain REPL it
runs every turn through four explicit phases:

1. PLAN   - ask the model for a JSON plan before answering.
2. RESPOND - answer the user, allowing typed tool calls (.md/.json helpers,
             bash, internet, ...).
3. MEMORY - extract important facts and fold a gist update into memory.
4. CONTEXT - check context usage and, when needed, compress old turns into
             the persistent gist.

Persistent files (under ``<workdir>/chat_memory/``)
---------------------------------------------------
``conversation_log.jsonl``    total, append-only record of every phase.
``conversation_gist.md``      rolling compressed memory.
``important_memory.json``     explicitly remembered facts.
``important_memory.md``       readable rendering of the above.
``context_state.json``        last context-window statistics.

Command line usage
------------------
``python rich_tui_chat.py``  (interactive; same env vars as other /agent
tools: ``LLM_BASE_URL``, ``LLM_REPL_MODEL``, ``CHAT_WORKDIR``).

Public API
----------
``RichTUIChat`` (alias ``LLMRepl``) is the main class.  ``send_message``
runs all four phases and returns the final answer string.
"""

import os, sys, json, time, re, uuid, threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_DIR = Path(os.getenv("AGENT_DIR", "/agent"))

if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

PROMPT_DIR = Path(os.getenv("AGENT_PROMPT_DIR", ".")) / "prompts"
if not PROMPT_DIR.exists():
    PROMPT_DIR = Path(SCRIPT_DIR) /"prompts"

# Todo: Use both /agent/prompts and curdir/prompts


PROMPT_DIR = PROMPT_DIR.resolve()

def _load_dotenv(path: Path) -> None:
    try:
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or not line.startswith("#") or "=" not in line:
                    if not line.startswith("#"):
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception as exc:
        sys.stderr.write(f"Warning: failed to load env file {path}: {exc}\n")

_load_dotenv(AGENT_DIR / ".env")
_load_dotenv(Path.cwd() / ".env")

def get_gateway_ip() -> str:
    try:
        from get_ip import get_gateway_ip as _gw  # type: ignore
        return _gw()
    except Exception:
        return os.getenv("GATEWAY_IP", "127.0.0.1")

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
except Exception:
    class Console:  # type: ignore
        def print(self, msg, *a, **k): print(msg)
        def rule(self, title): print(f"--- {title} ---")
    class Markdown:  # type: ignore
        def __init__(self, text): self.text = text
    class Panel:  # type: ignore
        def __init__(self, content, title=None): self.content = content; self.title = title
    class Table:  # type: ignore
        def __init__(self, title=None): self.title = title
        def add_column(self, *a, **k): pass
        def add_row(self, *a, **k): pass
    console = Console()

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
except Exception:
    PromptSession = None  # type: ignore
    FileHistory = None  # type: ignore

try:
    from openai_error_handling import classify_api_error, Action  # type: ignore
except Exception:
    class Action:  # type: ignore
        ABORT = "abort"; RETRY = "retry"; BACKOFF = "backoff"
    def classify_api_error(exc):  # type: ignore
        return Action.ABORT, 0.0

try:
    from agent_tools import (
    TOOL_DEFINITIONS, TOOL_MAP
    )
    BASE_TOOL_MAP = TOOL_MAP
    BASE_TOOL_SCHEMAS = TOOL_DEFINITIONS
except Exception:
    BASE_TOOL_MAP = {}
    BASE_TOOL_SCHEMAS = []
    def _run_bash(command: str) -> str: return "run_bash unavailable"
    def _read_file(path: str) -> str: return "read_file unavailable"
    def _read_file_lines(path: str, start_line: int = 1, end_line=None) -> str: return "read_file_lines unavailable"
    def _search_file(path: str, query: str) -> str: return "search_file unavailable"
    def _list_files(path: str = ".") -> str: return "list_files unavailable"
    def _write_file(path: str, content: str) -> str: return "write_file unavailable"
    def _now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Skill System Integration
from skill_system.tool_registry import registry as tool_registry
from skill_system.integration import SKILLS_ROOT, skills_manager as active_skills_mgr

from prompt_generator import PromptGenerator

def register_core_tools():
    """Registers the base tools into the ToolRegistry."""
    # Map tool definitions to their implementations
    import logging as _logging
    for tool_def in TOOL_DEFINITIONS:
        name = tool_def["function"]["name"]
        func = TOOL_MAP.get(name)
        if func is None:
            _logging.warning(f"No implementation found for tool '{name}'. Skipping registration.")
            continue

        if name not in tool_registry.list_tools():
            description = tool_def["function"].get("description", f"Tool {name}")
            parameters = tool_def["function"].get("parameters", {})
            tool_registry.register(name, description, func, parameters)
        else:
            _logging.info(f"Tool '{name}' is already registered. Skipping.")

register_core_tools()

def _role(m):
    if isinstance(m, dict): return str(m.get("role", ""))
    return str(getattr(m, "role", ""))
def _content(m):
    if isinstance(m, dict): v = m.get("content", "")
    else: v = getattr(m, "content", "")
    return "" if v is None else str(v)
def _tool_calls(m):
    if isinstance(m, dict): return m.get("tool_calls")
    return getattr(m, "tool_calls", None)
def _call_name(tc):
    if isinstance(tc, dict):
        f = tc.get("function", {}) or {}; return str(f.get("name", ""))
    f = getattr(tc, "function", None); return str(getattr(f, "name", "")) if f is not None else ""
def _call_args(tc):
    if isinstance(tc, dict):
        f = tc.get("function", {}) or {}; raw = f.get("arguments", "{}")
    else:
        f = getattr(tc, "function", None); raw = getattr(f, "arguments", "{}") if f is not None else "{}"
    if isinstance(raw, dict): return raw
    try:
        p = json.loads(raw or "{}"); return p if isinstance(p, dict) else {}
    except Exception: return {}
def _call_id(tc):
    if isinstance(tc, dict): return str(tc.get("id", ""))
    return str(getattr(tc, "id", ""))

@dataclass
class UsageTracker:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    last_prompt_tokens: int = 0
    context_limit: int = 4096
    per_turn: list = field(default_factory=list)
    def record(self, usage, turn=None):
        if usage is None: return
        p = getattr(usage, "prompt_tokens", 0) or 0
        c = getattr(usage, "completion_tokens", 0) or 0
        if p == 0 and self.last_prompt_tokens: p = self.last_prompt_tokens
        self.prompt_tokens += p
        self.completion_tokens += c
        self.calls += 1
        self.last_prompt_tokens = p
        self.per_turn.append({"turn": turn, "prompt": p, "completion": c})
    @property
    def context_pct(self):
        if not self.context_limit: return 0.0
        return 100.0 * self.last_prompt_tokens / self.context_limit
    def summary(self):
        return (f"calls={self.calls} in={self.prompt_tokens} out={self.completion_tokens} "
                f"ctx={self.last_prompt_tokens}/{self.context_limit} ({self.context_pct:.0f}%)")

def discover_context_window(base_url, model, default=4096):
    import requests
    root = base_url.rstrip("/")
    if root.endswith("/v1"): root = root[:-3]
    try:
        r = requests.get(f"{root}/api/ps", timeout=5); r.raise_for_status()
        for m in r.json().get("models", []):
            if m.get("name") == model or m.get("model") == model:
                return int(m["context_length"])
    except Exception: pass
    try:
        r = requests.post(f"{root}/api/show", json={"model": model}, timeout=5); r.raise_for_status()
        info = r.json().get("model_info", {}) or {}
        for k, v in info.items():
            if k.endswith(".context_length") and isinstance(v, int): return v
    except Exception: pass
    return default

# Aliases + module-level tool wrappers.
LLMRepl = RichTUIChat if 'RichTUIChat' in globals() else None

from dataclasses import dataclass as _dc


@_dc
class MemoryEntry:
    fact_id: str
    timestamp: str
    text: str
    importance: float
    tags: list
    source: str
    retention: str = "permanent"


class ConversationMemory:
    def __init__(self, workdir: Path):
        self.workdir = Path(workdir).resolve()
        self.memory_dir = self.workdir / "chat_memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.memory_dir / "conversation_log.jsonl"
        self.gist_path = self.memory_dir / "conversation_gist.md"
        self.important_json_path = self.memory_dir / "important_memory.json"
        self.important_md_path = self.memory_dir / "important_memory.md"
        self.context_state_path = self.memory_dir / "context_state.json"
        self._lock = threading.RLock()
        self.gist = self._load_gist()
        self.important = self._load_important()
        self.turn_counter = self._count_log_turns()
        self.clear_transient_memories()

    def _load_gist(self):
        try:
            if self.gist_path.exists():
                return self.gist_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        return ""

    def _load_important(self):
        out = []
        try:
            if self.important_json_path.exists():
                raw = json.loads(self.important_json_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, dict):
                            out.append(MemoryEntry(
                                fact_id=item.get("id", ""),
                                timestamp=item.get("timestamp", ""),
                                text=item.get("text", ""),
                                importance=float(item.get("importance", 0.5)),
                                tags=list(item.get("tags", []) or []),
                                source=item.get("source", ""),
                                retention=item.get("retention", "permanent")
                            ))
        except Exception:
            pass
        return out

    def _save_gist(self):
        self.gist_path.write_text((self.gist.strip() or "") + "\n", encoding="utf-8")

    def _save_important(self):
        payload = [
            {"id": e.fact_id, "timestamp": e.timestamp, "text": e.text,
             "importance": e.importance, "tags": e.tags, "source": e.source, "retention": e.retention}
            for e in self.important
        ]
        self.important_json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        lines = ["# Important Remembered Facts", ""]
        for e in sorted(self.important, key=lambda x: -x.importance):
            ts = f" ({', '.join(e.tags)})" if e.tags else ""
            lines.append(
                f"- [{e.retention} | {e.importance:.2f}] {e.text}{ts}"
            )
        self.important_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


    def clear_transient_memories(self):
        with self._lock:
            self.important = [e for e in self.important if e.retention == "permanent"]
            self._save_important()
    def _count_log_turns(self):
        if not self.log_path.exists():
            return 0
        n = 0
        try:
            with open(self.log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("kind") == "turn":
                        n += 1
        except Exception:
            pass
        return n

    def append_log(self, kind, payload):
        rec = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, "payload": payload}
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                fh.flush()

    def add_important(self, text, importance=0.7, tags=None, source="model", retention="permanent"):
        if not text or not str(text).strip():
            raise ValueError("Cannot remember an empty fact.")
        importance = max(0.0, min(1.0, float(importance)))
        from datetime import datetime, timezone
        entry = MemoryEntry(
            fact_id=uuid.uuid4().hex[:10],
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            text=str(text).strip(),
            importance=importance,
            tags=list(tags or []),
            source=source,
            retention=retention
        )
        with self._lock:
            self.important.append(entry)
            self._save_important()
        self.append_log("remembered", {"entry": {"fact_id": entry.fact_id, "text": entry.text,
                        "importance": entry.importance, "tags": entry.tags, "source": entry.source}})
        return entry

    def important_context_text(self):
        if not self.important:
            return "No explicitly remembered facts yet."
        lines = []
        for e in sorted(self.important, key=lambda x: -x.importance):
            tags = f" tags={e.tags}" if e.tags else ""
            lines.append(f"- [{e.importance:.2f}] {e.text}{tags}")
        return "\n".join(lines)

    def gist_context_text(self):
        return self.gist.strip() if self.gist.strip() else "(none yet)"

    def save_context_state(self, state):
        try:
            self.context_state_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(f"Failed to write context state: {exc}") from exc

    def begin_turn(self):
        with self._lock:
            self.turn_counter += 1
            return self.turn_counter

    def maybe_compress_context(self, chat, messages, context_pct, reason):
        max_messages = int(os.getenv("CHAT_CONTEXT_LIMIT", "40"))
        threshold = float(os.getenv("CHAT_CONTEXT_THRESHOLD", "70"))
        keep_recent = int(os.getenv("CHAT_KEEP_RECENT", "8"))
        if context_pct < threshold and len(messages) <= max_messages:
            return False, messages
        system_message = messages[0] if messages and _role(messages[0]) == "system" else None
        start = 1 if system_message is not None else 0
        if len(messages) - start <= keep_recent:
            trimmed = ([messages[0]] if system_message is not None else []) + messages[-keep_recent:]
            while trimmed and _role(trimmed[-1]) == "tool":
                trimmed.pop()
            self.append_log("context_trimmed_hard", {"reason": reason, "kept": len(trimmed)})
            return False, trimmed
        compressible = messages[start:len(messages) - keep_recent]
        recent = messages[len(messages) - keep_recent:]
        try:
            summary = chat._summarize_messages(compressible, self.gist, self.turn_counter)
        except Exception as exc:
            console.print(f"[bold yellow]Context compression failed: {exc}; trimming instead.[/bold yellow]")
            self.append_log("compression_failed", {"reason": str(exc)})
            idx = 0
            while idx < len(recent) and _role(recent[idx]) == "tool":
                idx += 1
            trimmed = ([messages[0]] if system_message is not None else []) + recent[idx:]
            return False, trimmed
        from datetime import datetime, timezone
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        new_parts = [f"## Compression @ {ts} (reason={reason})"]
        if self.gist.strip():
            new_parts.append("Previous gist:\n" + self.gist.strip())
        new_parts.append("Newly compressed turns:\n" + summary.strip())
        with self._lock:
            self.gist = "\n\n".join(new_parts)
            try:
                self._save_gist()
            except Exception as exc:
                console.print(f"[bold yellow]Could not persist gist: {exc}[/bold yellow]")
        new_messages = []
        if system_message is not None:
            new_messages.append(system_message)
        idx = 0
        while idx < len(recent) and _role(recent[idx]) == "tool":
            idx += 1
        new_messages.extend(recent[idx:])
        self.append_log("context_compressed", {
            "reason": reason, "context_pct": context_pct,
            "compressed": len(compressible), "kept": len(recent) - idx,
            "gist_chars": len(self.gist),
        })
        return True, new_messages

PLANNING_SYSTEM_PROMPT = """You are the PLANNING phase of a multi-phase assistant.
Return ONLY a JSON object with keys: goal, steps, tools_needed, memory_candidates, answer_shape.
No prose outside JSON."""
EXTRACTION_SYSTEM_PROMPT = """You are the MEMORY phase of a multi-phase assistant.
Return ONLY a JSON object with keys:
important, gist_addition, created_files.
important is a list of objects {"text","importance","tags", "retention"}.
retention must be either 'permanent' or 'transient'
Use 'permanent' for enduring user preferences, identity,
ongoing projects, and facts likely to matter across future sessions. "
Use 'transient' for temporary plans, current tasks, and
short-lived situational details.
Filter question: Would retaining this information improve a future conversation
after the current conversation has ended?"""

class RichTUIChat:
    def __init__(self, model=None, base_url=None, api_key=None, workdir=None):
        self.workdir = Path(workdir or os.getenv("CHAT_WORKDIR", os.getcwd())).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.model = model or os.getenv("LLM_REPL_MODEL", "gemma4:e4b")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", os.getenv("LLM_BASE_URL", f"http://{get_gateway_ip()}:11434/v1"))
        self.api_key = api_key or os.getenv("LLM_REPL_API_KEY", "ollama")
        from openai import OpenAI as _OpenAI
        self.client = _OpenAI(base_url=self.base_url, api_key=self.api_key)
        self.memory = ConversationMemory(self.workdir)
        self.usage = UsageTracker()
        try:
            self.usage.context_limit = discover_context_window(self.base_url, self.model)
        except Exception:
            self.usage.context_limit = int(os.getenv("CHAT_CONTEXT_TOKENS", "4096"))

        self.promptgen = PromptGenerator(prompts_dir=str(PROMPT_DIR))

        self.base_system_prompt = self.promptgen.generate_prompt("chat")

        self._state_lock = threading.RLock()
        self.messages = []

        # Initialize Skill System
        self.skills_mgr = active_skills_mgr
        # print("Rich chat tools: %s", tool_registry.list_tools())
        # print("Discovered skills: %s", self.skills_mgr.catalog)

        # discover_skills is already called in integration.py

        self.system_prompt = self._build_system_prompt()
        self.messages.append({"role": "system", "content": self.system_prompt})
        self.max_tool_rounds = int(os.getenv("CHAT_MAX_TOOL_ROUNDS", "12"))
        self._shutdown_done = False
        self.prompt_session = None
        try:
            if PromptSession is not None:
                hp = self.workdir / ".rich_tui_history"
                self.prompt_session = PromptSession(history=FileHistory(str(hp)) if FileHistory else None)
        except Exception:
            self.prompt_session = None

        self.tool_map = self._build_tool_map()
        self.tool_schemas = self._build_tool_schemas()
        # print("Working REPL tools: %s", list(self.tool_map.keys()))

        self.turn_id = self.memory.turn_counter
        console.print(f"[dim]Context window: {self.usage.context_limit} | workdir: {self.workdir}[/dim]")
        import logging
        logger = logging.getLogger("UnifiedAgent")

    def _build_system_prompt(self):
        skills_summary = self.skills_mgr.get_catalog_summary()
        if skills_summary:
            skills_summary = (
                "### Available Skills\n"
                "Use the discovered skill catalog to identify relevant capabilities "
                "and follow the applicable skill instructions when needed.\n\n"
                f"{skills_summary}"
            )
        return (f"{self.base_system_prompt}\n\n {skills_summary}\n\n"
                f"### Conversation gist (compressed memory)\n{self.memory.gist_context_text()}\n\n"
                f"### Explicitly remembered facts\n{self.memory.important_context_text()}\n")

    def _refresh_system_prompt(self):
        with self._state_lock:
            self.system_prompt = self._build_system_prompt()
            if self.messages and _role(self.messages[0]) == "system":
                self.messages[0] = {"role": "system", "content": self.system_prompt}

    def _text_completion(self, messages, tools=None, tool_choice=None, temperature=0.2):
        kwargs = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return self.client.chat.completions.create(**kwargs)

    def _summarize_messages(self, messages, previous_gist, turn_id):
        rendered = []
        for m in messages:
            role = _role(m).upper()
            c = _content(m)
            if not c:
                calls = _tool_calls(m)
                if calls:
                    c = "[tool calls: " + ", ".join(_call_name(x) for x in calls) + "]"
            if c:
                rendered.append(f"{role}: {c}")
        text = "\n".join(rendered)[:12000]
        msgs = [
            {"role": "system", "content": "You compress conversations into durable gists. Preserve decisions, facts, preferences, constraints. Be concise (<=400 words). Output markdown."},
            {"role": "user", "content": f"Previous gist:\n{previous_gist or '(none)'}\n\nConversation:\n{text}\n\nWrite updated gist."},
        ]
        resp = self._text_completion(msgs, temperature=0.0)
        self.usage.record(getattr(resp, "usage", None), turn=len(self.messages))
        return _content(resp.choices[0].message) or "(no summary produced)"

    def _build_tool_map(self):
        tm = {}
        tm.update(BASE_TOOL_MAP or {})
        tm.update({
            "create_markdown_file": lambda **kw: self._tool_create_markdown_file(**kw),
            "create_json_file": lambda **kw: self._tool_create_json_file(**kw),
            "append_markdown": lambda **kw: self._tool_append_markdown(**kw),
            "remember": lambda **kw: self._tool_remember(**kw),
            "list_remembered": lambda **kw: self._tool_list_remembered(**kw),
            "context_status": lambda **kw: self._tool_context_status(**kw),
            "get_gist": lambda **kw: self.memory.gist_context_text(),
        })
        return tm

    def _build_tool_schemas(self):
        schemas = []
        try:
            schemas.extend(list(BASE_TOOL_SCHEMAS or []))
        except Exception:
            pass
        schemas.extend([
            {"type": "function", "function": {"name": "create_markdown_file", "description": "Create/overwrite a .md file in working dir.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
            {"type": "function", "function": {"name": "create_json_file", "description": "Create/overwrite a .json file in working dir (valid JSON).", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
            {"type": "function", "function": {"name": "append_markdown", "description": "Append text to a .md file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
            {"type": "function", "function": {"name": "remember", "description": "Remember an important fact.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "importance": {"type": "number"}, "tags": {"type": "array", "items": {"type": "string"}}, "retention": {"type": "string", "enum": ["permanent", "transient"]}}, "required": ["text"]}}},
            {"type": "function", "function": {"name": "list_remembered", "description": "List remembered facts.", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "context_status", "description": "Context usage and memory stats.", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "get_gist", "description": "Return compressed gist.", "parameters": {"type": "object", "properties": {}}}},
        ])
        return schemas

    def _safe_path(self, path, suffix=None):
        cand = Path(path)
        if not cand.is_absolute():
            cand = self.workdir / cand
        cand = cand.resolve()
        try:
            cand.relative_to(self.workdir)
        except ValueError as exc:
            raise ValueError(f"Path escapes working directory: {path}") from exc
        if suffix and cand.suffix != suffix:
            raise ValueError(f"Expected suffix {suffix}, got {cand.suffix or '(none)'}")
        return cand

    def _tool_create_markdown_file(self, path, content):
        try:
            target = self._safe_path(path, ".md")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self.memory.append_log("file_created", {"path": str(target), "kind": "markdown", "chars": len(content)})
            return f"Created markdown file {target} ({len(content)} chars)."
        except Exception as exc:
            return f"Error creating markdown file: {exc}"

    def _tool_create_json_file(self, path, content):
        try:
            target = self._safe_path(path, ".json")
            parsed = json.loads(content)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            self.memory.append_log("file_created", {"path": str(target), "kind": "json"})
            return f"Created JSON file {target}."
        except json.JSONDecodeError as exc:
            return f"Error: invalid JSON ({exc})."
        except Exception as exc:
            return f"Error creating JSON file: {exc}"

    def _tool_append_markdown(self, path, content):
        try:
            target = self._safe_path(path, ".md")
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(content)
            return f"Appended {len(content)} chars to {target}."
        except Exception as exc:
            return f"Error appending markdown: {exc}"

    def _tool_remember(self, text, importance=0.7, tags=None, retention="permanent"):
        try:
            entry = self.memory.add_important(text, importance=importance, tags=tags, source="model", retention=retention)
            self._refresh_system_prompt()
            return f"Remembered (id={entry.fact_id}, importance={entry.importance:.2f})."
        except Exception as exc:
            return f"Error remembering fact: {exc}"

    def _tool_list_remembered(self):
        if not self.memory.important:
            return "No remembered facts."
        return "\n".join(
            f"- [{e.retention} | {e.importance:.2f}] {e.text}"
            + (f" ({', '.join(e.tags)})" if e.tags else "")
            for e in sorted(self.memory.important, key=lambda x: -x.importance)
        )
    def _tool_context_status(self):
        return (f"context_pct={self.usage.context_pct:.1f}% ({self.usage.last_prompt_tokens}/{self.usage.context_limit}); "
                f"messages={len(self.messages)}; gist_chars={len(self.memory.gist)}; "
                f"remembered={len(self.memory.important)}; turn={self.turn_id}.")

    def _parse_json(self, text):
        if not isinstance(text, str):
            return None
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        else:
            s = text.find("{"); e = text.rfind("}")
            if s != -1 and e != -1 and e > s:
                candidate = text[s:e + 1]
            else:
                candidate = text.strip()
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            s = text.find("{")
            if s == -1:
                return None
            depth = 0
            for i in range(s, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(text[s:i + 1])
                            return parsed if isinstance(parsed, dict) else None
                        except json.JSONDecodeError:
                            return None
        return None

    def _phase_plan(self, user_input):
        console.print("[bold cyan]Phase 1/4 - Planning...[/bold cyan]")
        messages = [{"role": "system", "content": PLANNING_SYSTEM_PROMPT},
                    {"role": "user", "content": f"User request:\n{user_input}"}]
        raw = ""
        try:
            response = self._text_completion(messages, temperature=0.1)
            raw = _content(response.choices[0].message)
            self.usage.record(getattr(response, "usage", None), turn=len(self.messages))
        except Exception as exc:
            console.print(f"[bold yellow]Planning call failed: {exc}; using fallback plan.[/bold yellow]")
        plan = self._parse_json(raw)
        if not isinstance(plan, dict):
            plan = {"goal": user_input, "steps": ["Answer the request directly.", "Use tools if they help."],
                    "tools_needed": [], "memory_candidates": [], "answer_shape": "Concise, helpful reply.",
                    "_planning_failed": True, "_raw": raw}
        plan.setdefault("goal", user_input)
        plan.setdefault("steps", [])
        plan.setdefault("tools_needed", [])
        plan.setdefault("memory_candidates", [])
        plan.setdefault("answer_shape", "")
        self.memory.append_log("plan", {"turn": self.turn_id, "user": user_input, "plan": plan, "raw": raw})
        return plan

    def _format_plan(self, plan):
        lines = [f"**Goal:** {plan.get('goal', '')}"]
        steps = plan.get("steps") or []
        if steps:
            lines.append("**Steps:**")
            for idx, step in enumerate(steps, 1):
                lines.append(f"{idx}. {step}")
        tools = plan.get("tools_needed") or []
        if tools:
            lines.append("**Likely tools:** " + ", ".join(str(t) for t in tools))
        shape = plan.get("answer_shape")
        if shape:
            lines.append(f"**Reply shape:** {shape}")
        return "\n".join(lines)

    def _phase_respond(self, user_input, plan):
        console.print("[bold cyan]Phase 2/4 - Responding (tool use enabled)...[/bold cyan]")
        with self._state_lock:
            self.messages.append({"role": "user", "content": user_input})
            self._trim_context()
            self._refresh_system_prompt()
        tool_calls_made = []
        final_content = ""
        round_index = 0
        while round_index < self.max_tool_rounds:
            round_index += 1
            with self._state_lock:
                augmented_system = {"role": "system", "content": self.system_prompt +
                                     "\n\n## Internal plan for this reply (do not quote verbatim)\n" +
                                     json.dumps(plan, indent=2, default=str)}
                call_messages = [augmented_system] + [m for m in self.messages if _role(m) != "system"]
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=call_messages, tools=self.tool_schemas, tool_choice="auto")
            except Exception as exc:
                action, delay = classify_api_error(exc)
                if action in (Action.RETRY, Action.BACKOFF):
                    console.print(f"[bold yellow]API error ({action}); retrying in {delay}s...[/bold yellow]")
                    time.sleep(delay)
                    continue
                err = f"API error: {exc}"
                console.print(f"[bold red]{err}[/bold red]")
                with self._state_lock:
                    if self.messages and _role(self.messages[-1]) == "user":
                        self.messages.pop()
                return err, tool_calls_made
            self.usage.record(response.usage, turn=len(self.messages))
            console.print(f"[dim]{self.usage.summary()}[/dim]")
            msg = response.choices[0].message
            if _tool_calls(msg):
                with self._state_lock:
                    self.messages.append(msg)
                console.print(f"[bold blue][*] Model requested {len(_tool_calls(msg))} tool call(s).[/bold blue]")
                for tc in _tool_calls(msg):
                    name = _call_name(tc)
                    args = _call_args(tc)
                    preview = str(args)
                    if len(preview) > 200:
                        preview = preview[:200] + "..."
                    console.print(f"  [blue]tool:[/blue] {name}({preview})")
                    result = self._execute_tool(name, args)
                    rp = result if len(result) <= 400 else result[:400] + "..."
                    console.print(f"  [green]result:[/green] {rp}")
                    tool_calls_made.append({"name": name, "args": args, "result": result})
                    with self._state_lock:
                        self.messages.append({"role": "tool", "tool_call_id": _call_id(tc),
                                              "name": name, "content": result})
                self.memory.append_log("tool_round", {"turn": self.turn_id, "round": round_index,
                                                      "calls": tool_calls_made[-len(_tool_calls(msg)): ]})
                continue
            final_content = _content(msg) or ""
            with self._state_lock:
                self.messages.append({"role": "assistant", "content": final_content})
            if final_content.strip():
                from rich.markdown import Markdown as _MD
                from rich.panel import Panel as _Panel
                console.print(_Panel(_MD(final_content), title="Assistant"))
            else:
                console.print("[bold red]Assistant: (No response)[/bold red]")
            break
        if not final_content and round_index >= self.max_tool_rounds:
            final_content = "(stopped: reached maximum tool rounds)"
            console.print(f"[bold yellow]{final_content}[/bold yellow]")
            with self._state_lock:
                self.messages.append({"role": "assistant", "content": final_content})
        return final_content, tool_calls_made

    def _execute_tool(self, name, args):

        func = self.tool_map.get(name)
        if func:
            try:
                return str(func(**args))
            except TypeError as exc:
                return f"Error: bad arguments for {name}: {exc}"
            except Exception as exc:
                return f"Error executing {name}: {exc}"

        # 2. Fallback to the global tool registry (Core tools + Discovered Skills)
        # This handles 'system-info', 'run_bash', etc.
        result = tool_registry.execute(name, **args)
        if not result.startswith("Error:"):
            return result

        if func is None:
            return f"Error: tool '{name}' not found."


    def _phase_memory(self, user_input, assistant_response, plan, tool_calls):
        console.print("[bold cyan]Phase 3/4 - Memory & gist update...[/bold cyan]")
        self.turn_id = self.memory.begin_turn()
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": (f"User request:\n{user_input}\n\nPlan:\n{json.dumps(plan, default=str)}\n\n"
                                          f"Assistant final answer:\n{assistant_response}\n\nTool calls: {json.dumps(tool_calls, default=str)[:4000]}")},
        ]
        important_items = []
        gist_addition = ""
        created_files = []
        try:
            response = self._text_completion(messages, temperature=0.1)
            self.usage.record(getattr(response, "usage", None), turn=len(self.messages))
            parsed = self._parse_json(_content(response.choices[0].message))
            if isinstance(parsed, dict):
                important_items = list(parsed.get("important") or [])
                gist_addition = str(parsed.get("gist_addition") or "")
                created_files = list(parsed.get("created_files") or [])
        except Exception as exc:
            console.print(f"[bold yellow]Memory extraction failed: {exc}[/bold yellow]")
            self.memory.append_log("memory_extraction_failed", {"turn": self.turn_id, "error": str(exc)})
        remembered_ids = []
        for item in important_items:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                importance = float(item.get("importance", 0.7))
            except (TypeError, ValueError):
                importance = 0.7
            tags = [str(t) for t in (item.get("tags") or [])]
            retention = item.get("retention", "transient")
            if retention not in ("permanent", "transient"):
                retention = "transient"

            entry = self.memory.add_important(
                text,
                importance=importance,
                tags=tags,
                source=f"turn {self.turn_id}",
                retention=retention,
            )
            remembered_ids.append(entry.fact_id)
        if gist_addition.strip():
            prev = self.memory.gist
            with self.memory._lock:
                self.memory.gist = ((prev + "\n\n") if prev.strip() else "") + f"### Turn {self.turn_id}\n" + gist_addition.strip()
                try:
                    self.memory._save_gist()
                except Exception as exc:
                    console.print(f"[bold yellow]Could not persist gist: {exc}[/bold yellow]")
        self._refresh_system_prompt()
        console.print("[bold cyan]Phase 4/4 - Context check & compression...[/bold cyan]")
        compressed, new_messages = self.memory.maybe_compress_context(self, list(self.messages), self.usage.context_pct, "post_turn")
        with self._state_lock:
            if compressed:
                self.messages = new_messages
                if not (self.messages and _role(self.messages[0]) == "system"):
                    self.messages.insert(0, {"role": "system", "content": self.system_prompt})
                else:
                    self.messages[0] = {"role": "system", "content": self.system_prompt}
                console.print("[green]Compressed conversation into gist.[/green]")
        self.memory.save_context_state({
            "turn": self.turn_id, "context_pct": self.usage.context_pct,
            "last_prompt_tokens": self.usage.last_prompt_tokens, "context_limit": self.usage.context_limit,
            "messages": len(self.messages), "remembered": len(self.memory.important),
            "gist_chars": len(self.memory.gist), "compressed_now": compressed,
        })
        self.memory.append_log("turn", {
            "turn": self.turn_id, "user": user_input, "plan": plan,
            "assistant": assistant_response, "tool_calls": tool_calls,
            "remembered_ids": remembered_ids, "created_files": created_files,
            "context_pct": self.usage.context_pct, "compressed": compressed,
        })
        if remembered_ids:
            console.print(f"[green]Remembered {len(remembered_ids)} fact(s).[/green]")

    # Public convenience aliases ------------------------------------------------
    def plan_reply(self, user_input: str):
        """Run only the planning phase (Phase 1)."""
        return self._phase_plan(user_input)

    def phase_respond(self, user_input: str, plan=None):
        """Run the responding phase (Phase 2)."""
        if plan is None:
            plan = self._phase_plan(user_input)
        return self._phase_respond(user_input, plan)

    def update_memory(self, user_input, assistant_response, plan, tool_calls=None):
        """Run the memory/compression phase (Phase 3/4)."""
        return self._phase_memory(user_input, assistant_response, plan, tool_calls or [])

    def context_usage(self):
        return self._tool_context_status()

    def remembered_facts(self):
        return [e.text for e in self.memory.important]

    def gist(self):
        return self.memory.gist_context_text()

    def send_message(self, user_input):
        user_input = (user_input or "").strip()
        if not user_input:
            return ""
        try:
            self.turn_id = self.memory.begin_turn()
        except Exception:
            pass
        plan = self._phase_plan(user_input)
        from rich.markdown import Markdown as _MD
        from rich.panel import Panel as _Panel
        console.print(_Panel(_MD(self._format_plan(plan)), title="Plan (Phase 1)"))
        final_content, tool_calls = self._phase_respond(user_input, plan)
        self._phase_memory(user_input, final_content, plan, tool_calls)
        self.memory.save_context_state({"turn": self.turn_id, "context_pct": self.usage.context_pct,
            "last_prompt_tokens": self.usage.last_prompt_tokens, "context_limit": self.usage.context_limit,
            "messages": len(self.messages)})
        return final_content

    def _trim_context(self):
        with self._state_lock:
            max_messages = int(os.getenv("CHAT_CONTEXT_LIMIT", "40"))
            if len(self.messages) <= max_messages:
                return
            keep_count = max(1, max_messages - 1)
            tail = self.messages[-keep_count:]
            while tail and _role(tail[0]) == "tool":
                tail = tail[1:]
            self.messages = [self.messages[0]] + tail

    def run(self):
        console.rule("[bold green]Rich TUI Chat Started[/bold green]")
        console.print(f"Model: [bold]{self.model}[/bold] | Base URL: [bold]{self.base_url}[/bold]")
        console.print("Commands: /q /clear /sys <prompt> /model <name> /history /memory /remember <text> /context /help")
        while True:
            try:
                if self.prompt_session is not None:
                    user_input = self.prompt_session.prompt("\nUser > ")
                else:
                    user_input = input("\nUser > ")
                user_input = (user_input or "").strip()
                if not user_input:
                    continue
                if user_input in ("/q", "/quit", "/exit"):
                    console.print("[bold red]Goodbye![/bold red]")
                    break
                if user_input == "/clear":
                    with self._state_lock:
                        self.messages = [{"role": "system", "content": self.system_prompt}]
                    console.print("[yellow]Conversation context cleared (memory files retained).[/yellow]")
                    continue
                if user_input.startswith("/sys "):
                    self.base_system_prompt = user_input[5:].strip()
                    self._refresh_system_prompt()
                    console.print("[yellow]System prompt updated.[/yellow]")
                    continue
                if user_input.startswith("/model "):
                    self.model = user_input[7:].strip()
                    console.print(f"[yellow]Model switched to: {self.model}[/yellow]")
                    continue
                if user_input.startswith("/remember "):
                    fact = user_input[len("/remember "):].strip()
                    if fact:
                        entry = self.memory.add_important(fact, importance=0.8, source="user")
                        self._refresh_system_prompt()
                        console.print(f"[green]Remembered (id={entry.fact_id}).[/green]")
                    continue
                if user_input == "/history":
                    from rich.table import Table as _T
                    table = _T(title="Conversation History")
                    table.add_column("Role", style="cyan")
                    table.add_column("Content", style="white")
                    with self._state_lock:
                        snapshot = list(self.messages)
                    for m in snapshot:
                        c = _content(m)
                        if len(c) > 100:
                            c = c[:100] + "..."
                        table.add_row(_role(m), c)
                    console.print(table)
                    continue
                if user_input == "/memory":
                    console.print(Panel(self.memory.important_context_text(), title="Remembered facts"))
                    console.print(Panel(self.memory.gist_context_text(), title="Gist"))
                    continue
                if user_input == "/context":
                    console.print(self._tool_context_status())
                    continue
                if user_input == "/help":
                    console.print("/q /clear /sys /model /history /memory /remember /context /help")
                    continue
                self.send_message(user_input)
            except EOFError:
                console.print("\n[bold red]Goodbye![/bold red]")
                break
            except KeyboardInterrupt:
                console.print("\n[bold red]Goodbye![/bold red]")
                break
            except Exception as exc:
                import logging as _logging
                _logging.exception("Unexpected REPL error: %s", exc)
                console.print(f"[bold red]Unexpected error: {exc}[/bold red]")

    def shutdown(self):
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            self.memory.append_log("shutdown", {"turn": self.turn_id, "messages": len(self.messages)})
        except Exception:
            pass

    def __enter__(self):
        return self
    def __exit__(self, *exc):
        self.shutdown()
        return False

# Backwards-compatible aliases
LLMRepl = RichTUIChat
ChatApp = RichTUIChat
RichTUI = RichTUIChat

# Module-level tool wrappers for compatibility
def tool_run_bash(command):
    return _run_bash(command)
def tool_read_file(path):
    return _read_file(path)
def tool_write_file(path, content):
    return _write_file(path, content)
def now():
    return _now()

def main():
    try:
        chat = RichTUIChat()
    except Exception as exc:
        console.print(f"[bold red]Failed to start chat: {exc}[/bold red]")
        return 1
    try:
        with chat:
            chat.run()
    except KeyboardInterrupt:
        console.print("\n[bold red]Goodbye![/bold red]")
    except Exception as exc:
        console.print(f"[bold red]Fatal error: {exc}[/bold red]")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
