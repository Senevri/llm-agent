#!/usr/local/bin/python

import os
import sys
import shlex
import json
import logging
import tempfile
from datetime import timedelta, datetime
import subprocess
import textwrap
import time
import queue
import threading
import atexit
import re
import uuid
import shutil
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Any, List, Callable, NamedTuple, Optional, Union, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial

from prompt_generator import PromptGenerator, find_prompt_dir
from agent_dispatcher import AgentDispatcher, Status as AgentStatus
from backend import LLMBackend, BACKEND_MAP

from openai import OpenAI

PROMPT_DIR = find_prompt_dir()

# --- Paths / environment discovery -------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_DIR = Path(os.getenv("AGENT_DIR", "/agent"))
PROFILE_PATH = Path(os.getenv("LLM_REPL_PROFILE_PATH", str(Path.cwd() / ".llm_user_profile_v2.json")))
LOG_FILE = Path(os.getenv("LLM_REPL_LOG_FILE", str(Path.cwd() / "llm_repl_v2.log")))
MAX_CONTEXT_MESSAGES = int(os.getenv("LLM_REPL_MAX_CONTEXT", "40"))
JOB_CLEANUP_INTERVAL = int(os.getenv("LLM_REPL_JOB_CLEANUP_INTERVAL", "3600"))

# Make /agent importable, mirroring run_agent.py.
sys.path.insert(0, str(AGENT_DIR))


PROFILER_PROMPT = """
You are a profiling agent. Your task is to maintain a JSON profile of the user.
You maintain a JSON profile of the user.
Current profile:\n{profile_json}\n
User message this turn (the ONLY evidence you may use):
<<<
{user_input}
>>>
Rules:
- Do NOT infer anything from the assistant's reply. The assistant's
text is not evidence about the user.
- Record what the user stated about themselves (preferences,
goals, expertise, constraints, recurring context).
- Never use credential language ('expert', 'mastery', 'authority',
'principal') unless the user used it about themselves.
- If the user's message contains nothing that updates the profile
(e.g. 'mm', 'thanks', 'ok', a question, or agreement), do not change the profile.)
"""

def _load_dotenv(path: Path = AGENT_DIR / ".env") -> None:
    """Load simple KEY=VALUE env files without overriding existing vars."""
    try:
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception as e:  # pragma: no cover - startup diagnostics
        sys.stderr.write(f"Warning: failed to load env file {path}: {e}\n")


_load_dotenv()


def get_gateway_ip() -> str:
    try:
        from get_ip import get_gateway_ip as _get_gateway_ip
        return _get_gateway_ip()
    except Exception:
        return os.getenv("GATEWAY_IP", "127.0.0.1")


def _env_default(key: str, fallback: str) -> str:
    return os.getenv(key, fallback)


def parse_command(text: str):
    try:
        parts = shlex.split(text)
    except ValueError as e:
        return None, [], {}, str(e)

    if not parts:
        return None, [], {}, None

    command = parts[0].lstrip("/")
    positional = []
    kwargs = {}

    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            kwargs[key] = value
        else:
            positional.append(part)

    return command, positional, kwargs, None

try:
    from get_ip import get_gateway_ip as _gw
except Exception:
    def _gw() -> str:
        return "127.0.0.1"

try:
    from openai_error_handling import classify_api_error, Action
except Exception:
    class Action:
        ABORT = "abort"
        RETRY = "retry"
        BACKOFF = "backoff"

    def classify_api_error(e):  # type: ignore
        return Action.ABORT, 0.0

try:
    from tools.internet_tools import (
        INTERNET_TOOL_DEFINITION_MAP, INTERNET_TOOL_MAP
    )
except Exception:
    INTERNET_TOOL_MAP = {}
    INTERNET_TOOL_DEFINITION_MAP = {}
    def search_internet(query: str, max_results: int = 5) -> str:  # type: ignore
        return "Internet search is not available."
    def get_weather(location: str) -> str:  # type: ignore
        return "Weather lookup is not available."

try:
    from tools.agent_tools import TOOL_MAP as BASE_TOOL_MAP, tools as BASE_TOOL_SCHEMAS
except Exception:
    BASE_TOOL_MAP = {}
    BASE_TOOL_SCHEMAS = []

from skill_system.tool_registry import ToolRegistry
from skill_system.skills_manager import SkillsManager
from skill_system.integration import SKILLS_ROOT

DEFAULT_MODEL = os.getenv("LLM_REPL_MODEL", "gemma4:e4b")
DEFAULT_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    os.getenv("LLM_BASE_URL", f"http://{get_gateway_ip()}:11434/v1"),
)
DEFAULT_API_KEY = os.getenv("LLM_REPL_API_KEY", "ollama")

# --- Rich / prompt_toolkit with safe fallbacks -----------------------------------
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    console = Console(
        file=sys.__stdout__,
        force_terminal=True,
        color_system="auto",
    )
except Exception:
    class Console:  # type: ignore
        def print(self, msg, *args, **kwargs):
            print(msg)
        def rule(self, title):
            print(f"--- {title} ---")
    class Markdown:  # type: ignore
        def __init__(self, text):
            self.text = text
    class Panel:  # type: ignore
        def __init__(self, content, title=None):
            self.content = content
            self.title = title
    class Table:  # type: ignore
        def __init__(self, title=None):
            self.title = title
        def add_column(self, *a, **k):
            pass
        def add_row(self, *a, **k):
            pass
    console = Console()

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    prompt_session = PromptSession(history=FileHistory(str(Path.cwd() / ".repl_history")))
except Exception:
    prompt_session = None

# --- Error hierarchy ---------------------------------------------------------------
class REPLError(Exception):
    """Base exception for LLMRepl V2."""
    pass


class APIError(REPLError):
    """Errors related to the LLM API."""
    pass


class ProfileError(REPLError):
    """Errors related to user profile management."""
    pass


class JobError(REPLError):
    """Errors related to background agent jobs."""
    pass


class StartupError(REPLError):
    """Errors occurring during REPL initialization."""
    pass


# --- Helper classes ---------------------------------------------------------------
@dataclass
class ContextSnapshot:
    """State packaging for the profiling worker."""
    user_input: str
    assistant_response: str
    history: List[Any]
    timestamp: float = field(default_factory=time.time)
    event_type: str = "turn_complete"


class UserProfileManager:
    """Thread-safe manager for user preferences and profile data."""

    def __init__(self, profile_path: Path = PROFILE_PATH):
        self.profile_path = Path(profile_path)
        self._lock = threading.RLock()
        with self._lock:
            self._profile_data: Dict[str, Any] = self._load_profile()

    def _load_profile(self) -> Dict[str, Any]:
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
                logging.error("Profile file did not contain a JSON object; ignoring.")
                return {}
            except Exception as e:
                logging.error(f"Failed to load profile: {e}")
                return {}
        return {}

    def save_profile(self) -> None:
        with self._lock:
            try:
                self.profile_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.profile_path, "w", encoding="utf-8") as f:
                    json.dump(self._profile_data, f, indent=2)
            except Exception as e:
                logging.error(f"Error saving profile: {e}")

    def get_profile_string(self) -> str:
        with self._lock:
            if not self._profile_data:
                return "No user profile available."
            return json.dumps(self._profile_data, indent=2)

    def update_profile(self, updates: Dict[str, Any]) -> None:
        with self._lock:
            self._profile_data.update(updates)
            self.save_profile()

    def set_profile_data(self, data: Dict[str, Any]) -> None:
        with self._lock:
            if not isinstance(data, dict):
                raise ProfileError(f"Expected dict for profile data, got {type(data)}")
            self._profile_data = data
            self.save_profile()

    @property
    def profile_data(self) -> Dict[str, Any]:
        with self._lock:
            return self._profile_data.copy()

    def __enter__(self) -> "UserProfileManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.save_profile()
        return False


# --- Logging setup (queue-decoupled) ---------------------------------------------
class LogQueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put(record)
        except Exception:
            self.handleError(record)


class LogQueueListener(threading.Thread):
    def __init__(self, log_queue: queue.Queue, formatter=None):
        super().__init__(daemon=True, name="LogQueueListener")
        self.log_queue = log_queue
        self.formatter = formatter
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()
        try:
            self.log_queue.put(None)
        except Exception:
            pass

    def run(self):
        while not self._stop_event.is_set():
            try:
                record = self.log_queue.get(timeout=1.0)
                if record is None:
                    break
                msg = self.formatter.format(record) if self.formatter else record.getMessage()
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
                self.log_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                sys.stderr.write(f"LogQueueListener error: {e}\n")


logger = logging.getLogger("LLMReplV2")
logger.setLevel(logging.DEBUG)
#logger.setLevel(logging.WARNING)
logger.propagate = False
_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
try:
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
except Exception as e:
    sys.stderr.write(f"Warning: could not create log file handler: {e}\n")

_log_queue = queue.Queue()
_log_handler = LogQueueHandler(_log_queue)
_log_handler.setFormatter(_fmt)
logger.addHandler(_log_handler)
_log_listener = LogQueueListener(_log_queue, _fmt)
try:
    _log_listener.start()
except Exception as e:
    sys.stderr.write(f"Warning: could not start log listener: {e}\n")

_active_repls = 0
_active_repls_lock = threading.Lock()


def _stop_log_listener() -> None:
    try:
        _log_listener.stop()
        _log_listener.join(timeout=2.0)
    except Exception:
        pass


atexit.register(_stop_log_listener)

# --- Profiling worker --------------------------------------------------------------
class ProfileWorker(threading.Thread):
    """Background worker that consumes profiling tasks and updates the user profile."""

    def __init__(self, repl: "LLMRepl", q: queue.Queue, batch_size: int = 3, time_threshold: float = 0.5):
        super().__init__(daemon=True, name="ProfileWorker")
        self.repl = repl
        self.queue = q
        self.batch_size = batch_size
        self.time_threshold = time_threshold
        self._stop_event = threading.Event()
        self.batch: List[ContextSnapshot] = []
        self.api=None
        self.console=None
        self.dispatcher = None

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.queue.put(None)
        except Exception:
            pass

    def run(self) -> None:
        logger.info("ProfileWorker thread started.")
        while not self._stop_event.is_set():
            try:
                snapshot = self.queue.get(timeout=1.0)
                if snapshot is None:
                    self._process_batch()
                    break
                self.batch.append(snapshot)
                if len(self.batch) >= self.batch_size:
                    self._process_batch()
                self.queue.task_done()
            except queue.Empty:
                if self.batch and (time.time() - self.batch[-1].timestamp >= self.time_threshold):
                    self._process_batch()
            except Exception as e:
                logger.exception(f"ProfileWorker error: {e}")
        logger.info("ProfileWorker thread shutting down.")

    def _process_batch(self) -> None:
        if not self.batch:
            return
        latest = self.batch[-1]
        self.repl._apply_profile_update(latest.user_input, latest.assistant_response)
        self.batch = []

# --- CommandDispatcher -------------------------------------------------------------
class CommandDispatcher:
    def __init__(self, repl):
        self.repl = repl
        self.commands = {}

    def register(self, name, handler, help="", aliases=()):
        entry = {
            "handler": handler,
            "help": help,
        }
        self.commands[name] = entry

        for alias in aliases:
            self.commands[alias] = entry

    def dispatch(self, name, args, kwargs):
        entry = self.commands.get(name)

        if entry is None:
            return None

        return entry["handler"](self.repl, *args, **kwargs)

    def load(self, commands_dict: Dict[str, Callable], command_definitions: Dict[str, Dict[str, Any]]):
        for name, handler in commands_dict.items():
            help_text = command_definitions[name].get("help", "")
            aliases = command_definitions[name].get("aliases", [])
            self.register(name, handler, help_text, aliases)

    def get_help(self):
        # Generate help from unique command entries.
        ...

def clear_command(repl, *args, **kwargs):
    with repl._state_lock:
        repl.messages = [
            {"role": "system", "content": repl.system_prompt}
        ]
    console.print("[yellow]Conversation history cleared.[/yellow]")

def profile_command(repl, *args, **kwargs):
    console.print(Panel(repl.profile_manager.get_profile_string(), title="User Profile"))
    console.print("[yellow]Profile saved.[/yellow]")

def quit_command(repl, *args, **kwargs):
    console.print("[yellow]Goodbye![/yellow]")
    repl.shutdown()
    return "quit"

def stub(repl, *args, **kwargs):
            return "stub"

def help(repl, *args, **kwargs):
    _, command_definitions = repl.load_commands()
    cmd_help = "\n".join([f"    /{k}: {v['help']}" for k, v in command_definitions.items()])
    help_text = textwrap.dedent(f"""
        Commands:
            /help - show this help
            /backend <backend> port=<port> model=<model> - switch backend
        """)
    console.print(help_text + cmd_help)

def system_prompt_command(repl, *args, **kwargs):
    with repl._state_lock:
        repl.base_system_prompt = args[0].strip()
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    console.print("[yellow]System prompt updated.[/yellow]")

def backend(repl, *args, **kwargs):

    if len(args) < 1:
        console.print(f"availabe backends: {', '.join(BACKEND_MAP.keys())} (default: {repl.backend})")
        return
    with repl._state_lock:
        if args[0] not in BACKEND_MAP.keys():
            console.print(f"[red]Backend {args} not found in {BACKEND_MAP.keys()}[/red]")
            return
        repl.backend = args[0]

        api = LLMBackend(backend=repl.backend)
        api.port = kwargs.get("port", api.port)
        api.model = kwargs.get("model", api.model)
        repl.client, repl.model = api.get_client()

        repl.prompt_gen.reload_profiles()
        repl.base_system_prompt = repl.prompt_gen.generate_prompt(repl.current_role)
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]

    console.print(f"[yellow]Backend switched to: {repl.backend}[/yellow]")

def history(repl, *args, **kwargs):
    table = Table(title="Conversation History")
    table.add_column("Role", style="cyan")
    table.add_column("Content", style="white")
    with repl._state_lock:
        snapshot = list(repl.messages)
    for m in snapshot:
        role = _role(m)
        content = m["content"] if isinstance(m, dict) else (getattr(m, "content", "") or "")
        content = str(content or "")
        if len(content) > 100:
            content = content[:100] + "..."
        table.add_row(role, content)
    console.print(table)

def role(repl, *args, **kwargs):
    with repl._state_lock:
        repl.current_role = args[0]
        repl.prompt_gen.reload_profiles()
        repl.base_system_prompt = repl.prompt_gen.generate_prompt(repl.current_role)
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    console.print(f"[yellow]Role switched to: {repl.current_role}[/yellow]")

def model(repl, *args, **kwargs):
    if len(args) < 1:
        console.print(f"availabe models: {', '.join(repl.api.endpoint.list_models())} (default: {repl.model})")
        return
    repl.model = args[0].strip()
    console.print(f"[yellow]Model switched to: {repl.model}[/yellow]")

class LoopTask:
    import threading
    def __init__(self, repl, task):
        self.repl: LLMRepl = repl
        self.started_at = None
        self.ends_at = None
        self.task = task
        self.commands = queue.Queue()
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.agent = None
        self.backend_settings = {
            "backend": self.repl.backend,
            "port": self.repl.api.port,
            "model": self.repl.model,
        }
        self.thread = None


    def start(self):
        self.started_at = datetime.now()
        self.repl.loop_task = self
        self.thread = threading.Thread(
            target=self.run,
            kwargs={"stop_event": self.stop_event},
            daemon=True)
        self.thread.start()
        return self

    def get_output(self):
        if not self.agent:
            return
        dispatcher, jid, info = self.agent
        return dispatcher.get_job_output(jid)

    def _run_loop(self):
        while not self.stop_event.is_set():
            if self.pause_event.wait(timeout=0.5):
                continue

            if self.agent:
                dispatcher, jid, info = self.agent
                if dispatcher.get_job_status(jid) in [AgentStatus.COMPLETED, AgentStatus.FAILED]:
                    with self.repl._state_lock:
                        output = dispatcher.get_job_output(jid)
                        console.print(Markdown(output))
                        #self.repl.messages += [{"role": "assistant", "content": output}]

                    if self.check_timeout():

                        dispatcher.shutdown(stop_owned_jobs=True)
                        break
                    else:
                        jid, info = dispatcher.dispatch_agent_job(self.task, session_name=info["session_name"])
                        with self.repl._jobs_lock:
                            self.repl._jobs[jid] = info
                        self.agent = (dispatcher, jid, info)
            else:
                dispatcher = AgentDispatcher(prompt_gen=self.repl.prompt_gen)
                dispatcher.backend="mistral"
                # dispatcher.backend = self.backend_settings.get("backend", "mistral")
                # dispatcher.port = self.backend_settings.get("port")
                # dispatcher.model = self.backend_settings.get("model")

                session_name=f"agent-loop-{uuid.uuid4().hex[:8]}"
                jid, info = dispatcher.dispatch_agent_job(self.task, session_name=session_name)
                self.agent = (dispatcher, jid, info)

            if self.ends_at and datetime.now() > self.ends_at:
                output = dispatcher.get_job_output(jid)
                console.print(output)
                self.stop()

    def run(self, *args, **kwargs):
        logger.info(f"Starting LoopTask... {args} {kwargs}")
        try:
            self._run_loop()
        except Exception as e:
            logger.error(f"LoopTask error: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        if self.agent:
            dispatcher, jid, info = self.agent
            dispatcher.shutdown(stop_owned_jobs=True)
        self.repl.loop_task = None
        self.agent = None
        self.thread = None


    def check_timeout(self):
        if self.ends_at and datetime.now() > self.ends_at:
            self.stop()
            return True
        return False

    def stop(self):
        self.stop_event.set()
        self.started_at=None

    def set_end(self, end):
        self.ends_at = end

    def pause(self):
        self.pause_event.set()

    def resume(self):
        self.pause_event.clear()



def loop (repl, *args, **kwargs):

    if "start" in args:
        task_prompt = kwargs.get("task", None)
        if not task_prompt:
            console.print("[red]No task prompt provided[/red]")
            return

        if repl.loop_task and repl.loop_task.is_running():
            console.print("[red]Loop task already running[/red]")
            return


        loop_task = LoopTask(repl, task_prompt)
        loop_task.started_at = datetime.now()
        # add parsing of timedelta
        hours = int(kwargs.get("hours", 0))
        minutes = int(kwargs.get("minutes", 0))
        seconds = int(kwargs.get("seconds", 0))
        # form a time delta

        # add the delta to the current time
        delta = timedelta(hours=hours, minutes=minutes, seconds=seconds)
        loop_task.set_end(loop_task.started_at + delta)
        loop_task.start()
        return loop_task

    elif "stop" in args:
        if repl.loop_task:
            # get output from any agents
            console.print(repl.loop_task.get_output())
            repl.loop_task.stop()
            repl.loop_task.cleanup()
        else:
            console.print("[red]No loop task running[/red]")

    elif "check" in args:
        if repl.loop_task:
            console.print(repl.loop_task.get_output())
        else:
            console.print("[red]No loop task running[/red]")
    return None



# --- Main REPL --------------------------------------------------------------------
class LLMRepl:
    def __init__(self, model=DEFAULT_MODEL, base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY,
                 profile_path: Path = PROFILE_PATH):
        global _active_repls
        self._state_lock = threading.RLock()
        self._jobs_lock = threading.RLock()
        self._jobs = {}
        self._shutdown_done = False
        self._profile_path = Path(profile_path)
        self.backend="ollama"
        self.loop_task=None

        with _active_repls_lock:
            _active_repls += 1

        try:
            self.api = LLMBackend(backend=self.backend)
            self.api.model = model

            self.client, _ = self.api.get_client()
        except Exception as e:
            raise StartupError(f"Failed to create OpenAI client: {e}") from e

        self.model = model
        try:
            self.profile_manager = UserProfileManager(profile_path=self._profile_path)
        except Exception as e:
            raise StartupError(f"Failed to initialize user profile: {e}") from e


        try:
            self.prompt_gen = PromptGenerator(prompts_dir=str(PROMPT_DIR))
            self.current_role = "repl"
            self.base_system_prompt = self.prompt_gen.generate_prompt(self.current_role)
        except ImportError:
            prompt_gen = None

            self.base_system_prompt = "You are a helpful assistant. You have access to skills and tools"

        self.skills_manager = SkillsManager(SKILLS_ROOT)
        self.skills_manager.discover_skills()

        # with self._state_lock:
        #     self.system_prompt = self._build_system_prompt()
        #     self.messages = [{"role": "system", "content": self.system_prompt}]

        with self._state_lock:
            self.system_prompt = self._build_system_prompt()
            self.messages: List[Dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]

        self.profile_queue = queue.Queue()
        self.worker = ProfileWorker(self, self.profile_queue)

        self.tool_registry = create_tool_registry(self)
        self.tool_schemas = self.tool_registry.get_all_schemas()

        self.worker.start()

        logger.info(
            "Registered %d tools: %s",
            len(self.tool_schemas),
            self.tool_registry.list_tools(),
        )
        logger.info("Discovered skills: %s", self.skills_manager.catalog.keys())

        atexit.register(self.shutdown)

    def __enter__(self) -> "LLMRepl":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.shutdown()
        return False

    def shutdown(self) -> None:
        global _active_repls
        if self._shutdown_done:
            return
        self._shutdown_done = True

        logger.info("Shutting down LLMRepl...")

        # Stop all jobs cleanly using the new dispatcher
        if hasattr(self, 'dispatcher'):
            self.dispatcher.shutdown(stop_owned_jobs=True)

        if self.loop_task:
            self.loop_task.stop()
            self.loop_task.cleanup()

        try:
            self.worker.stop()
            self.worker.join(timeout=5.0)
        except Exception as e:
            logger.error(f"Error stopping profile worker: {e}")

        try:
            self.profile_manager.save_profile()
        except Exception as e:
            logger.error(f"Error saving profile: {e}")

        with _active_repls_lock:
            _active_repls = max(0, _active_repls - 1)
            if _active_repls == 0:
                _stop_log_listener()

        logger.info("LLMRepl shutdown complete.")
    def _build_system_prompt(self) -> str:
        profile_str = self.profile_manager.get_profile_string()

        sections = [
            self.base_system_prompt,
            "### User Profile\n"
            "The following is what is known about the user. Use this to personalize responses:\n"
            f"{profile_str}",
        ]

        skills_summary = self.skills_manager.get_catalog_summary()
        if skills_summary:
            sections.append(
                "### Available Skills\n"
                "Use the discovered skill catalog to identify relevant capabilities "
                "and follow the applicable skill instructions when needed.\n\n"
                f"{skills_summary}"
            )

        return "\n\n".join(sections)


    def _trim_context(self) -> None:
        # Safe to call with or without holding _state_lock (RLock).
        with self._state_lock:
            if len(self.messages) <= MAX_CONTEXT_MESSAGES:
                return
            keep_count = MAX_CONTEXT_MESSAGES - 1
            tail = self.messages[-keep_count:]
            while tail and _role(tail[0]) == "tool":
                tail = tail[1:]
            self.messages = [self.messages[0]] + tail

    def _normalize_messages(self, messages, provider):
        normalized = []

        for message in messages:
            msg = dict(message)

            if provider == "mistral":
                msg.pop("reasoning_content", None)

            normalized.append(msg)

        return normalized

    def _request_chat_completion(self, messages: List[Dict[str, Any]], tools=None, tool_choice=None):
        return self.client.chat.completions.create(
            model=self.model,
            messages=self._normalize_messages(messages, self.backend),
            tools=tools or [],
            tool_choice=tool_choice or "auto",
        )

    def _execute_tools(self, tool_calls: List[Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for tc in tool_calls:
            name = getattr(tc.function, "name", "")

            try:
                args = json.loads(tc.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object.")

                logger.info("Executing tool %s with %s", name, args)

                result = self.tool_registry.execute(name, **args)

                if result is None:
                    result = "Error: tool returned no result (None)."

                content = result if isinstance(result, str) else str(result)

            except Exception as e:
                logger.exception("Tool %s failed", name)
                content = f"Error executing tool {name}: {e}"

            # Always return a result, including for malformed arguments and errors.
            results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": content,
            })

        return results

    def send_message(self, user_input: str) -> str:
        with self._state_lock:
            self.messages.append({"role": "user", "content": user_input})
            self._trim_context()
            current_messages = list(self.messages)

        # Start timing the entire turn (includes tool calls and retries)
        start_time = time.time()

        while True:
            try:
                response = self._request_chat_completion(current_messages, tools=self.tool_schemas, tool_choice="auto")
                msg = response.choices[0].message
                assistant_msg = msg.model_dump(exclude_none=True)

                if msg.tool_calls:
                    with self._state_lock:
                        self.messages.append(assistant_msg)
                    current_messages.append(assistant_msg)
                    tool_results = self._execute_tools(msg.tool_calls)
                    with self._state_lock:
                        self.messages.extend(tool_results)
                    current_messages.extend(tool_results)
                    continue

                content = msg.content or ""
                with self._state_lock:
                    self.messages.append({"role": "assistant", "content": content})

                # Calculate elapsed time
                elapsed = time.time() - start_time

                if content:
                    console.print(Panel(Markdown(content), title="Assistant"))
                else:
                    console.print("[bold red]Assistant: (No response)[/bold red]")

                # Only print time if it exceeds 5 seconds
                if elapsed > 5.0:
                    console.print(f"[dim]⏱️  Turn completed in {elapsed:.2f}s[/dim]")

                self._enqueue_profile_snapshot(user_input, content)
                return content

            except Exception as e:
                if not self._handle_api_error(e):
                    return f"API Error: {e}"

    def _handle_api_error(self, e: Exception) -> bool:
        try:
            action, delay = classify_api_error(e)
        except Exception:
            action, delay = Action.ABORT, 0.0
        if action in (Action.RETRY, Action.BACKOFF):
            logger.warning(f"API error {action}: {e}. Waiting {delay}s...")
            try:
                time.sleep(delay)
            except Exception:
                pass
            return True
        logger.error(f"Fatal API error: {e}")
        with self._state_lock:
            if self.messages and _role(self.messages[-1]) == "user":
                self.messages.pop()
        return False

    def _enqueue_profile_snapshot(self, user_input: str, assistant_response: str) -> None:
        with self._state_lock:
            history = list(self.messages)
        snapshot = ContextSnapshot(
            user_input=user_input,
            assistant_response=assistant_response,
            history=history,
            timestamp=time.time(),
            event_type="turn_complete",
        )
        self.profile_queue.put(snapshot)

    def _apply_profile_update(self, user_input: str, assistant_response: str) -> None:
        try:
            profile_data = self.profile_manager.profile_data
            prompt = PROFILER_PROMPT.replace("{profile_json}", json.dumps(profile_data, indent=2)).replace("{user_input}", user_input)
            response = self._request_chat_completion(
                [{"role": "system", "content": "You are a helpful assistant that outputs ONLY JSON."},
                 {"role": "user", "content": prompt}],
                tools=None,
                tool_choice=None,
            )
            content = response.choices[0].message.content
            updated_json = self._robust_json_extract(content)
            if updated_json is not None:
                with self._state_lock:
                    self.profile_manager.set_profile_data(updated_json)
                    self.system_prompt = self._build_system_prompt()
                    if self.messages and _role(self.messages[0]) == "system":
                        self.messages[0] = {"role": "system", "content": self.system_prompt}
                logger.debug("User profile updated by worker.")
        except Exception as e:
            logger.error(f"Profile update failed: {e}")

    def _robust_json_extract(self, text: str) -> Optional[Dict[str, Any]]:
        if not isinstance(text, str):
            return None
        # Fenced code block first.
        pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end + 1]
            else:
                json_str = text.strip()

        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                return parsed
            return None
        except json.JSONDecodeError:
            return self._balanced_braces_extract(text)

    def _balanced_braces_extract(self, text: str) -> Optional[Dict[str, Any]]:
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

    # --- Job management -----------------------------------------------------------

    def _render_tool_list(self) -> str:
        return "\n".join(
            f"- `{s['function']['name']}` — {s['function']['description']}"
            for s in self.tool_schemas
    )

    def _dispatch_agent_job(self, task: str, profile: str = "software-dev", backend="ollama", model: Optional[str] = None, max_turns: int = 40, timeout: int = 1800) -> str:
        # use AgentDispatcher
        if not hasattr(self, 'dispatcher'):
            self.dispatcher = AgentDispatcher(
                agent_dir=str(AGENT_DIR),
                prompt_gen=self.prompt_gen,
            )

        model_override = os.getenv(f"AGENT_MODEL_{backend.upper()}") or os.getenv("AGENT_MODEL")
        if model_override:
            self.dispatcher.model = model_override

        if model:
            self.dispatcher.model = model


        job_id, job = self.dispatcher.dispatch_agent_job(task, profile=profile, max_turns=max_turns, timeout=timeout)
        with self._jobs_lock:
            self._jobs[job_id] = job

        logger.info(f"Job {job_id} dispatched.")

        # return job_id
        return (
            f"Dispatched {job_id} (profile={profile}). Running in background.\n"
            f"Workspace: {job['workspace']}\nLog: {job['log']}\n"
            f"Poll with check_job('{job_id}') or list_jobs()."
        )

        # dispatcher.active_jobs is a dict



    def _job_watchdog(self, job_id: str, timeout: int) -> None:
        time.sleep(timeout)
        with self._jobs_lock:
            job = self._jobs.get(job_id)

            # if job and job["proc"].poll() is None: #NO PROC IN JOB
            if job:
                logger.warning(f"Job {job_id} timed out after {timeout}s. Killing.")
                self._kill_job_internal(job_id)

    def _kill_job_internal(self, job_id: str) -> None:
        if hasattr(self, 'dispatcher'):
            self.dispatcher.stop_job(job_id)


    def _check_job(self, job_id:str) -> str:
        try:
            log_text = self.dispatcher.get_job_output(job_id, tail_chars=1500)
            tail = log_text[-1500:]
        except Exception as e:
            tail = f"(log error: {e})"

        job_status = self.dispatcher.get_job_status(job_id)
        return (
            f"{job_id} {job_status['status']} (exit: {job_status['exit_code']})\n"
            f"Workspace: {job_status['workspace']}\n"
            f"--- log tail ---\n{tail}"
        )


    def _list_jobs(self) -> str:
        with self._jobs_lock:
            self._jobs = self.dispatcher.active_jobs

            if not self._jobs:
                return "No jobs dispatched."

            lines = []
            for jid, j in self._jobs.items():
            # use dispatch there is no proc
                status = j["status"]
                elapsed = time.time() - j["start"]
                lines.append(f"{jid}: {status} ({elapsed:.0f}s, profile={j['profile']})")
            return "\n".join(lines)


    def load_commands(self):

        command_definitions = {
            "quit": {
                "aliases":  ["quit", "q", "exit"],
                "help": "",
            },
            "clear": {
                "help": "reset"
            },
            "sys": {
                "help": "<prompt> set system prompt",
            },
            "model": {
                "help": "<name> change model",
            },

            "history": {
                "help": "show context",
            },
            "profile": {
                "help": "view profile",
            },
            "role": {
                "help": "<name> change role",
            },
            "backend": {
                "help": "<name> change backend",
            },
            "help": {
                "help": "show help",
            },
            "loop": {
                "help": "<start|stop> hours=0 minutes=0 seconds=0 task=<prompt> loop task",
            }
        }


        # ---

        commands = {
            "quit": quit_command,
            "clear": clear_command,
            "sys": system_prompt_command,
            "model": model,
            "history": history,
            "profile": profile_command,
            "role": role,
            "backend": backend,
            "help" : help,
            "loop": loop
        }

        # let's get unique commoands:
        return commands, command_definitions


    def run(self) -> None:
        try:
            commands, command_definitions = self.load_commands()

            self.cmd_dispatcher = CommandDispatcher(self)

            self.cmd_dispatcher.load(commands, command_definitions)


            command_help = ",".join(
                f'[bold]/{k}[/bold] {v.get("help", "")}'
                for k, v in command_definitions.items()
                )

            console.rule("[bold green]LLM REPL Started (Profiled V2)[/bold green]")
            console.print(f"Model: [bold]{self.model}[/bold] | Base URL: [bold]{self.client.base_url}[/bold]")
            console.print(f"Commands: {command_help}")

            try:
                from prompt_toolkit.patch_stdout import patch_stdout
            except ImportError:
                from contextlib import nullcontext as patch_stdout

            self.loop_task = None

            with patch_stdout(True):
                while True:
                    try:
                        if prompt_session is not None:
                            user_input = prompt_session.prompt("\nUser > ")
                        else:
                            user_input = input("\nUser > ")
                        user_input = (user_input or "").strip()

                        command, args, params, errors = parse_command(user_input)

                        if not user_input:
                            continue

                        status = None
                        if command in self.cmd_dispatcher.commands:
                            status = self.cmd_dispatcher.dispatch(command, args, params)
                            if status:
                                logger.info(f"Command status: {status}")
                                if status == "quit":
                                    break
                                if isinstance(status, LoopTask):
                                    self.loop_task = status
                            continue
                        # Let's mark that the message was sent
                        console.print(Markdown("---"))
                        response = self.send_message(user_input)

                        # if response:
                        #     console.print(Panel(Markdown(response), title="Assistant"))
                    except EOFError:
                        console.print("[bold red]Goodbye![/bold red]")
                        break
                    except KeyboardInterrupt:
                        console.print("\n[bold red]Goodbye![/bold red]")
                        break
                    except Exception as e:
                        logger.exception(f"Unexpected error during REPL loop: {e}")
                        console.print(f"[bold red]Unexpected error: {e}[/bold red]")
        finally:
            self.shutdown()


def _role(m: Any) -> str:
    if isinstance(m, dict):
        return str(m.get("role", ""))
    return str(getattr(m, "role", ""))


# --- Module-level tool helpers ----------------------------------------------------
# --- Unified skill/tool registry -----------------------------------------------

REPL_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "dispatch_agent",
            "description": (
                "Dispatch an autonomous agent to run a multi-step task "
                "in a fresh, isolated workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Complete task brief: goal, constraints, and definition of done.",
                    },
                    "profile": {
                        "type": "string",
                        "description": "Agent profile. Defaults to engineering.",
                    },
                    "max_turns": {
                        "type": "integer",
                        "description": "Maximum agent turns.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum runtime in seconds.",
                    },
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_job",
            "description": "Check the status and recent logs of a dispatched agent job.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_jobs",
            "description": "List dispatched agent jobs and their statuses.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


def create_tool_registry(repl: LLMRepl) -> ToolRegistry:
    """Build a per-REPL registry from existing tool definitions and callables."""
    registry = ToolRegistry()

    # The definitions in agent_tools are the source of truth for the
    # core, internet, tmux, and context tools.
    definitions = list(BASE_TOOL_SCHEMAS or [])

    # Bind REPL-specific functions to this instance.
    repl_functions = {
        "dispatch_agent": lambda **kwargs: repl._dispatch_agent_job(**kwargs),
        "check_job": lambda job_id, **kwargs: repl._check_job(job_id),
        "list_jobs": lambda **kwargs: repl._list_jobs(),
    }

    definitions.extend(REPL_TOOL_DEFINITIONS)

    # Use the existing implementation map; the definitions supply schemas.
    implementations = dict(BASE_TOOL_MAP or {})
    implementations.update(INTERNET_TOOL_MAP or {})
    implementations.update(repl_functions)

    registered = set()

    for definition in definitions:
        function_def = definition.get("function", {})
        name = function_def.get("name")

        if not name or name in registered:
            if name in registered:
                logger.warning("Duplicate tool definition ignored: %s", name)
            continue

        func = implementations.get(name)
        if func is None:
            logger.warning(
                "No implementation found for tool '%s'; skipping registration.",
                name,
            )
            continue

        registry.register(
            name=name,
            description=function_def.get("description", f"Tool {name}"),
            func=func,
            parameters=function_def.get("parameters", {}),
        )
        registered.add(name)

    return registry


# Job manager facade retaining a simple API without changing LLMRepl internals.
class JobManager:
    def __init__(self, repl: LLMRepl):
        self.repl = repl

    def dispatch(self, task: str, profile: str = "engineering", max_turns: int = 40, timeout: int = 1800) -> str:
        return self.repl._dispatch_agent_job(task, profile=profile, max_turns=max_turns, timeout=timeout)

    def check(self, job_id: str) -> str:
        return self.repl._check_job(job_id)

    def list(self) -> str:
        return self.repl._list_jobs()


def _role(m: Any) -> str:
    if isinstance(m, dict):
        return str(m.get("role", ""))
    return str(getattr(m, "role", ""))


# --- Entry point ------------------------------------------------------------------
def main() -> int:
    try:
        repl = LLMRepl(
            model=os.getenv("LLM_REPL_MODEL", DEFAULT_MODEL),
            base_url=os.getenv("LLM_REPL_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.getenv("LLM_REPL_API_KEY", DEFAULT_API_KEY),
        )
    except Exception as e:
        logger.exception("Failed to initialize REPL")
        try:
            console.print(f"[bold red]Failed to start REPL: {e}[/bold red]")
        except Exception:
            sys.stderr.write(f"Failed to start REPL: {e}\n")
        return 1


    try:
        with repl:
            repl.run()
    except KeyboardInterrupt:
        console.print("\n[bold red]Goodbye![/bold red]")
    except EOFError:
        console.print("[bold red]Goodbye![/bold red]")
    except Exception as e:
        logger.exception(f"Fatal REPL error: {e}")
        try:
            console.print(f"[bold red]Fatal REPL error: {e}[/bold red]")
        except Exception:
            sys.stderr.write(f"Fatal REPL error: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
