#!/usr/local/bin/python
import asyncio
import atexit
import json
import logging
import os
import platform
import queue
import secrets
import sys
import threading
import time
import yaml
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta, datetime
from functools import partial

from logging.handlers import RotatingFileHandler
from openai import OpenAI, APIConnectionError, APIError as AE, InternalServerError
from openai_error_handling import classify_api_error, Action
from pathlib import Path
from pprint import pformat
from typing import Dict, Any, List, Callable, NamedTuple, Optional, Union, Tuple

# Local imports
from agent_dispatcher import OldAgentDispatcher, Status as AgentStatus
from backend import LLMBackend, BACKEND_MAP
from background_util import run_in_background, BackgroundProcess
from command_dispatcher import CommandDispatcher, parse_command
from log_queue import LogQueueHandler, LogQueueListener
from loop_task import LoopTask, SimpleLoopTask, loop
from prompt_generator import PromptGenerator, find_prompt_dir
from slashcommands import load_commands, tools_command, load_config, save_config, Script
from user_profile_manager import UserProfileManager, ContextSnapshot
from compress import Compressor
from job_manager import JobManager
#from requests.exceptions import HTTPError


logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("profileworker").setLevel(logging.WARNING)

PROMPT_DIR = find_prompt_dir()

# --- Paths / environment discovery -------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_DIR = Path(os.getenv("AGENT_DIR", SCRIPT_DIR))
PROFILE_PATH = Path(os.getenv("LLM_REPL_PROFILE_PATH", str(Path.cwd() / ".llm_user_profile_v2.json")))
LOG_FILE = Path(os.getenv("LLM_REPL_LOG_FILE", str(Path.cwd() / "llm_repl_v2.log")))
MAX_CONTEXT_MESSAGES = int(os.getenv("LLM_REPL_MAX_CONTEXT", "40"))
JOB_CLEANUP_INTERVAL = int(os.getenv("LLM_REPL_JOB_CLEANUP_INTERVAL", "3600"))

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
# Make /agent importable, mirroring run_agent.py.
if AGENT_DIR not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from llm_utils import (
    size_bytes, estimate_tokens, normalize_messages, discover_candidate_dir,
    robust_json_extract, balanced_braces_extract, _role, Message)
from profileworker import ProfileWorker

def _load_dotenv(path: Path = AGENT_DIR / ".env") -> None:
    """Load simple KEY=VALUE env files without overriding existing vars."""
    try:
        if not path.exists():
            logger.info(f"Env file not found: {path}")
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

# --- Setup Logging ------------------------------------------------------------

# --- Setup Logging (Unified & Thread-Safe) ------------------------------------
from custom_logger import setup_logging

# 1. Initialize the robust wrapped logger (handles file + basic stream)
logger = setup_logging(
    "LLMReplV3", level="DEBUG" if os.getenv("DEBUG") else "WARNING",
    log_dir=Path.cwd() / "logs",
    colors=True
    )

# 2. OPTIONAL BUT RECOMMENDED: Remove the standard StreamHandler to prevent
# duplicate console prints, since the Queue Listener will handle console output safely.
for h in list(logger.handlers):
    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
        _log_fmt = h.formatter
        logger.removeHandler(h)
    elif isinstance(h, LogQueueHandler):
        logger.removeHandler(h)

if not _log_fmt:
    format_str = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    _log_fmt = logging.Formatter(format_str)
# 3. Add the thread-safe queue handler for console output (prevents prompt_toolkit garbling)
_log_queue = queue.Queue()
_log_handler = LogQueueHandler(_log_queue)
_log_handler.setFormatter(_log_fmt)
logger.addHandler(_log_handler)  # __getattr__ cleanly delegates this to the underlying logger

# 4. Start the listener
_log_listener = LogQueueListener(_log_queue, _log_fmt)
try:
    _log_listener.start()
except Exception as e:
    sys.stderr.write(f"Warning: could not start log listener: {e}\n")

def _stop_log_listener() -> None:
    try:
        _log_listener.stop()
        _log_listener.join(timeout=2.0)
    except Exception:
        pass

# 5. Register cleanup
atexit.register(_stop_log_listener)

print("Logger:", logger.name)
print("Handlers:")
for h in logger.handlers:
    print(f"  {type(h).__name__}: {id(h)}")
print("Propagation:", logger.propagate)

_active_repls = 0
_active_repls_lock = threading.Lock()

tool_logger=None


def get_gateway_ip() -> str:
    try:
        from get_ip import get_gateway_ip as _get_gateway_ip
        return _get_gateway_ip()
    except Exception:
        return os.getenv("GATEWAY_IP", "127.0.0.1")

candidate_dir = discover_candidate_dir(Path(__file__).parent.parent, Path("tools"))
sys.path.insert(0, str(candidate_dir))

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





try:
    from tools.internet_tools import (
        INTERNET_TOOL_DEFINITION_MAP, INTERNET_TOOL_MAP)

except (ImportError, Exception) as e:
    logger.warning("Failed to import internet tools.\nError: %s", str(e))
    INTERNET_TOOL_MAP = {}
    INTERNET_TOOL_DEFINITION_MAP = {}
    def search_internet(query: str, max_results: int = 5) -> str:  # type: ignore
        return "Internet search is not available."
    def get_weather(location: str) -> str:  # type: ignore
        return "Weather lookup is not available."

try:
    from tools import WORKSPACE_DIR
    from tools.agent_tools import TOOL_MAP as BASE_TOOL_MAP, tools as BASE_TOOL_SCHEMAS
except Exception:
    logger.error("Failed to import agent tools")
    BASE_TOOL_MAP = {}
    BASE_TOOL_SCHEMAS = []
    raise StartupError("Failed to import agent tools")
    exit(1)

from skill_system.tool_registry import ToolRegistry, ToolCallResult
from skill_system.skills_manager import SkillsManager
from skill_system.integration import SKILLS_ROOT

DEFAULT_MODEL = os.getenv("LLM_REPL_MODEL", "")
DEFAULT_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    os.getenv("LLM_BASE_URL", f"http://{get_gateway_ip()}:11434/v1"),
)
DEFAULT_API_KEY = os.getenv("LLM_REPL_API_KEY", "00000000")
DEFAULT_BACKEND = os.getenv("LLM_REPL_BACKEND", "ollama")

# --- Rich / prompt_toolkit with safe fallbacks -----------------------------------
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    console = Console(
        file=sys.__stdout__,
        force_terminal=True,
        color_system="auto",
    )

    from urllib.parse import urlparse
    from prompt_toolkit.styles import Style

    TOOLBAR_STYLE = Style.from_dict({
        "bottom-toolbar":      "noreverse bg:default #5f8787",
        "bottom-toolbar.meta": "noreverse #585858",
        "bottom-toolbar.sep":  "noreverse #3a3a3a",
        "bottom-toolbar.loop": "noreverse #5fafaf",
        "bottom-toolbar.warn": "noreverse #d78700",
    })


except Exception:
    logger.error("Failed to import rich")
    exit(1)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    # try to find history file
    possible_paths = [
        Path("/workspace"),
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path("./workspace")
    ]
    for path in possible_paths:
        if path.exists():
            history_path = path / ".repl_history"
            break
    else:
        history_path = Path.cwd() / ".repl_history"
except Exception:
    logger.error("Failed to import prompt_toolkit")
    prompt_session = None

try:
    from prompt_toolkit.patch_stdout import patch_stdout
except ImportError:
    from contextlib import nullcontext as patch_stdout





# --- Main REPL --------------------------------------------------------------------
class LLMRepl:
    def __init__(self, profile_path: Path = PROFILE_PATH):

        global _active_repls
        self._state_lock = threading.RLock()
        self._jobs_lock = threading.RLock()
        self._jobs = {}
        self._shutdown_done = False
        self._profile_path = Path(profile_path)
        self.backend=None
        self.loop_task=None
        self.api=None
        self.condensed_prompt = None
        self.notools=False
        self.current_role = "repl"
        self.tasks = {}
        self.max_context_messages = MAX_CONTEXT_MESSAGES
        self.current_bg_task = None
        self.config = {}
        self.model = None
        self.client = None
        self.last_message_time = None # todo, make a message class
        self.no_reply = False
        self.pending_user_inputs = queue.Queue()
        self.input_queue = queue.Queue()
        self.agent_active = False
        self.status = "ok"
        self.logger = logger

        with _active_repls_lock:
            _active_repls += 1


    def _init(
            self, repl_be=os.getenv("LLM_REPL_BASE_URL", "http://localhost"),
            port=os.getenv("LLM_REPL_PORT", 8080),
            model=None
            ):

        self.config["backend"] = os.getenv("LLM_REPL_BACKEND", repl_be)
        self.config["port"] = port
        self.console = console

        try:
            # Note: llm_repl mutates self.api, self.client,
            # and self.model based on the loaded config.
            self.api = load_config(self, model=model)
            self.client, discovered_model = self.api.get_client() # type: ignore
            self.model = discovered_model
        except Exception as e:
            logger.error(f"Failed to create OpenAI client: {e}")
            console.print(f"Failed to create OpenAI client: {e}\n")
            self.model = "(unknown)"

        try:
            self.profile_manager = UserProfileManager(profile_path=self._profile_path)
        except Exception as e:
            raise StartupError(f"Failed to initialize user profile: {e}") from e


        try:
            self.prompt_gen = PromptGenerator(prompts_dir=str(PROMPT_DIR))
            self.current_role = "repl"
            self.prompt_gen.platform = platform.system().lower()
            self.base_system_prompt = self.prompt_gen.generate_prompt(self.current_role)
        except ImportError:
            prompt_gen = None

            self.base_system_prompt = "You are a helpful assistant. You have access to skills and tools"

        self.skills_manager = SkillsManager(SKILLS_ROOT)
        self.skills_manager.discover_skills()

        # with self._state_lock:
        #     self.system_prompt = self._build_system_prompt()
        #     self.messages = [{"role": "system", "content": self.system_prompt}]

        self.tool_registry = create_tool_registry(self)
        self.tool_schemas = self.tool_registry.get_all_schemas()



        with self._state_lock:
            self.system_prompt = self._build_system_prompt()
            self.messages: List[Dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]

        self.profile_queue = queue.Queue()
        self.worker = ProfileWorker(self, self.profile_queue, time_threshold=10)


        self.worker.start()

        logger.info(
            "Registered %d tools: %s",
            len(self.tool_schemas),
            self.tool_registry.list_tools(),
        )
        logger.info("Discovered skills: %s", ", ".join(self.skills_manager.catalog.keys()))
        logger.set_console_level("WARNING")

        atexit.register(self.shutdown)

    def __enter__(self) -> "LLMRepl":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.shutdown()
        return False

    def check_all_context_use(self):

        messages_bytes = sum(
            size_bytes(msg)
            for msg in self.messages
        )


        # profile_bytes = sum(self.profile_manager.get_profile_string().encode("utf-8"))
        profile_bytes = 0 # included in system_prompt
        prompt_bytes = len(self.system_prompt.encode("utf-8"))
        total_bytes = messages_bytes + profile_bytes + prompt_bytes
        return total_bytes

    def _loop_remaining_safe(self):
        lt = getattr(self, "loop_task", None)
        if lt is None:
            return None
        try:
            if lt.ends_at is None or not lt.is_running():
                return None
            return str(lt.ends_at - datetime.now()).split(".")[0]
        except Exception:
            return None

    def _toolbar_fragments(self):
        try:
            f = self._status_fields()
            sep = ("class:bottom-toolbar.sep", " · ")
            out = [("class:bottom-toolbar", f["model"])]
            host = urlparse(f["base_url"]).netloc      # "(unset)" -> "" -> skipped
            if host:
                out += [sep, ("class:bottom-toolbar.meta", host)]
            cls = "class:bottom-toolbar.warn" if f["pct"] >= 80 else "class:bottom-toolbar"
            out += [sep, (cls, f"{f['pct']:.0f}%")]
            if self.agent_active:
                out.append(("class:bottom-toolbar.meta", "  👣"))
            remaining = self._loop_remaining_safe()
            if remaining:
                out.append(("class:bottom-toolbar.loop", f"  🔁 {remaining}"))
            return out
        except Exception:
            logger.debug("toolbar render failed", exc_info=True)
            return [("class:bottom-toolbar", "…")]

    def show(self):
        console.print(self.get_diagnostics())
        console.print(dir(self))

    def _check_profile_worker_health(self):
        if not self.worker.is_alive():
            logger.error("Profile worker thread is DEAD! Restarting...")
            self.worker = ProfileWorker(self, self.profile_queue, time_threshold=10)
            self.worker.start()

        queue_size = self.profile_queue.qsize()
        if queue_size > 10:
            logger.warning(f"Profile queue is backing up: {queue_size} items")

    def get_diagnostics(self):
        return {
            "model": self.model,
            "messages": len(self.messages),
            "context_bytes": self.check_all_context_use(),
            "usage": self.api.usage.summary(),
        }

    def save_conversation_history(self): # save_messages
        if not any(_role(msg) != "tool" for msg in self.messages[1:]):
            return
        with self._state_lock:
            logger.info("Saving conversation history...")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            repl_archive = Path.cwd() / "repl_messages"
            if not repl_archive.exists():
                repl_archive.mkdir()
            path = repl_archive / f"repl_messages-{stamp}.yaml"
            logger.info("Saving to %s", path)
            with open(path, "w", encoding="utf-8") as f:
                # Leave off system prompt
                yaml.dump([msg for msg in self.messages[1:] if _role(msg) != "tool"], f)

    def shutdown(self) -> None:

        global _active_repls

        if self._shutdown_done:
            return
        self._shutdown_done = True

        try:
            save_config(self)
        except Exception as e:
            logger.error(f"Error saving config: {e}")

        self.save_conversation_history()

        logger.info("Shutting down LLMRepl...")

        # Stop all jobs cleanly using the new dispatcher
        # if hasattr(self, 'dispatcher') and self.dispatcher:
        #     self.dispatcher.shutdown(stop_owned_jobs=True)

        if self.loop_task:
            self.loop_task.stop()
            if isinstance(self.loop_task, LoopTask):
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


        # Save messages, ignore tools NOT IN PROFILE DUH tags:[save messages]

        logger.info("LLMRepl shutdown complete.")
    def _build_system_prompt(self) -> str:
        profile_str = self.profile_manager.get_profile_string()

        sections = [
            self.base_system_prompt,
            "### User Profile\n"
            "Wat is known about the user; Use this to personalize responses:\n"
            f"{profile_str}",
        ]

        skills_summary = self.skills_manager.get_catalog_summary()
        if skills_summary:
            sections.append(
                "### Available Skills\n"
                "Use the discovered skill catalog to identify relevant capabilities, "
                "follow the applicable skill instructions.\n\n"
                f"{skills_summary}"
            )
        allowed_paths = self.tool_registry.get_allowed_paths()
        if allowed_paths:
            sections.append(
                "Allowed Paths. No access outside these paths + workspace\n"
               f"{allowed_paths}"
            )

        if self.api and self.client:
            try:
                if len(str(sections[:-1])) > self.api.context_limit:
                    compressor = Compressor(self.api, self.max_context_messages)
                    content = compressor.ai_compress(sections[1:-1], max_tokens=self.api.context_limit//2)

                    if content:
                        sections = [content, sections[-1]]
                        logger.warning (f"condensed system prompt to {content}")
            except APIConnectionError:
                if self.api:
                    logger.warning(f"{self.api.backend}: {self.api.base_url} is not reachable")
                else:
                    logger.warning("API is not reachable")
        sections.append(f"workspace: {str(WORKSPACE_DIR)}")
        return "\n".join(sections)


    def _trim_context(self, force: bool = False) -> None:
        with self._state_lock:
            snapshot = list(self.messages)
            anchor = len(snapshot)

        compressor = Compressor(self.api, self.max_context_messages)
        plan = compressor.plan(snapshot, force=force)
        if plan.reason == "none" or not plan.compress:
            logger.debug("Trim: no action (%s)", plan.reason)
            return

        summary = compressor.summarize(plan.compress)
        if not summary:
            logger.warning("Trim: summarizer returned no usable content; leaving intact")
            return

        summary_msg = {
            "role": "assistant",
            "content": f"[History]: {summary}",
        }

        # Disable unused tools TODO: Figure out better rules for this
        # + "LLM can ask for a tool" mechanism
        unused_tools = self.tool_registry.get_tool_call_counts_sorted()

        if unused_tools:
            max_count = unused_tools[0][1]
            threshold = max_count / 10

            for index, (tool_name, count) in enumerate(
                reversed(unused_tools)
            ):
                if count == 0:
                    self.tool_registry.disable_tool(tool_name)
                    continue

                original_index = len(unused_tools) - 1 - index

                if original_index < len(unused_tools) // 2 and count < threshold:
                    self.tool_registry.disable_tool(tool_name)    # math

        tool_message = {
            "role": "assistant",
            "content": f"[Disabled tools]: {", ".join(self.tool_registry._disabled_tools)}",
        }

        with self._state_lock:
            new_tail = self.messages[anchor:]

            self.messages = [
                self.messages[0],
                summary_msg,
                tool_message,
                *plan.keep,
                *new_tail
            ]




        try:
            self.save_conversation_history()
        except Exception:
            logger.exception("Trim: failed to archive conversation history")


    def _request_chat_completion(self, messages: List[Dict[str, Any]], tools=None, tool_choice=None):
        request_start_time = time.time()
        if self.backend == "mistral":
            if self.last_message_time and time.time() - self.last_message_time < 1:
                time.sleep(request_start_time - self.last_message_time)

        if self.notools or os.getenv("BITNET", "0") == "1":
            return self.client.chat.completions.create(
                model=self.model,
                messages=normalize_messages(messages, self.backend)
            )
        self.last_message_time = time.time()
        return self.client.chat.completions.create(
            model=self.model,
            messages=normalize_messages(messages, self.backend),
            tools=tools or [],
            tool_choice=tool_choice or "auto",
        )
    def _execute_tools(self, tool_calls: List[Any]) -> List[ToolCallResult]:
        results: List[ToolCallResult] = []
        with patch_stdout():
            console.print(
                f"[bold blue][*] Model requested {len(tool_calls)} tool call(s).[/bold blue]")

            for tc in tool_calls:
                name = getattr(tc.function, "name", "")

                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("Tool arguments must be a JSON object.")

                    preview = str(args)

                    if len(preview) > 200:
                        preview = preview[:200] + "..."

                    logger.info("Executing tool %s with %s", name, preview)
                    logger.debug("full args: %s", args)

                    console.print(f"  [blue]tool:[/blue] {name}({preview})")

                    result = self.tool_registry.execute(name, **args)

                    if result is None:
                        result = "Error: tool returned no result (None)."

                    content = result if isinstance(result, str) else str(result)
                    response_str = f"  [green]result:[/green] {content}"
                    panel = Panel(response_str, box = box.SIMPLE_HEAVY,
                                        border_style="none", padding=(0, 1, 2, 1))

                    console.print(panel)

                except Exception as e:
                    logger.exception("Tool %s failed", name)
                    content = f"Error executing tool {name} with args {args}: {e}"

                # Always return a result, including for malformed arguments and errors.
                results.append(ToolCallResult(tool_call_id=tc.id, name=name, content=content))

        return results

    def _get_tool_results(self, tool_calls) -> Optional[List[ToolCallResult]]:
        from pprint import pformat
        MAX_TOOL_RESULTS_CHARS = 4000

        tool_results = self._execute_tools(tool_calls)
        if not tool_results:
            logger.info("Tool call returned no results")
            return None
        with self._state_lock:
            global tool_logger
            if not tool_logger:
                tool_logger = setup_logging("ReplToolLogger", level="WARNING")
            tool_logger.info("Tool results: %s", pformat(str(tool_results)))
            result_length = len(str(tool_results))
            if  result_length> MAX_TOOL_RESULTS_CHARS:
                _mtr = MAX_TOOL_RESULTS_CHARS
                # generate hash
                _id =  f"#{secrets.token_hex(8)}"
                # msg was warning; changed to info since it _currently works_
                tool_logger.info(
                    "Tool results too long %s: %s",
                    _id,
                    pformat([t for t in tool_results])
                    )
                # truncate tool results
                for i, result in enumerate(tool_results):
                    result["content"] = (
                        f"Tool output truncated; original: {result_length} chars. "
                        f"see {tool_logger.log_file} for "
                        f"full output. tag: {_id}\n"
                        f"{result.to_message(_mtr).get('content')}"
                        )
                    tool_results[i] = result
        return tool_results

    def _start_background_send(self, user_input: str) -> bool:
        if self.status == "stop":
            return False
        self.agent_active = True
        self.current_bg_task = run_in_background(self.send_message)(user_input)
        return True
#
    def _loop_status_text(self) -> str:
        if self.loop_task is None:
            return "ᓚᘏᗢ"
        remaining = self.loop_task.get_remaining_time()   # now side-effect free
        return f"Loop: {remaining}" if remaining else "loop idle"

    def _toolbar_text(self) -> str:
        return f"{self.model} | {self.api.context_limit} | {self.backend}   {self._loop_status_text()}"

    def _draw_end_rule(self, newline=False):
        if newline:
            console.print("\n")
        console.rule(self._loop_status_text())
        self.no_reply = False        # keep this — it's the re-arm


    def send_message(self, user_input: str) -> str:

        needs_trim = False
        with self._state_lock:
            if self.status == "stop":
                return "stopped"
            if self.api.usage.last_prompt_tokens >= self.api.context_limit * 0.85:
                needs_trim = True
        # Release state lock

        if needs_trim:
            self._request_chat_completion(
                [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": ("running low on context, update and compress memories and todos, "
                                                "create a gist file, emergency trim at 90 percent context usage")}],
                tools=None, tool_choice=None
                )
            self._trim_context()
        with self._state_lock:
            if user_input:
                self.messages.append({"role": "user", "content": user_input})
            current_messages = list(self.messages)

        # Start timing the entire turn (includes tool calls and retries)
        start_time = time.time()
        warning_sent = False
        SEND_TIMEOUT = 60

        with patch_stdout():
            while True:
                # Let's mark that the message was sent
                # self._draw_end_rule(True)
                console.print(f"[dim]Thinking...   ({self.check_all_context_use()} bytes)[/dim]")
                if self.status == "stop":
                    self.current_bg_task.stop()
                    return "stopped"
                self.no_reply = False
                if self.api.usage.context_pct >= 80.0 and not warning_sent:
                    # warn llm.
                    try:
                        warning = self.prompt_gen.generate_prompt(
                            "warning", {
                                "snippets": ["context_size_warning"]
                            },
                            context_pct=self.api.usage.context_pct,
                            remaining_tokens=self.api.usage.remaining_tokens
                            )
                    except Exception as e:
                        logger.error(f"Error generating prompt: {e}")
                        raise e

                    console.rule(f"[dim]warning - {self.api.usage.summary()}[dim]")
                    current_messages.append({"role": "system", "content": warning})
                    warning_sent = True
                try:
                    # json.dumps(self.tool_schemas) # defensive validation
                    self.agent_active = True
                    response = self._request_chat_completion(current_messages, tools=self.tool_schemas, tool_choice="auto")
                    msg = response.choices[0].message
                    # print((self.api.model, self.api.port, self.api.base_url))
                    # print("CONTENT:", repr(msg.content))
                    # print("TOOL CALLS:", msg.tool_calls)
                    # print("FINISH REASON:", response.choices[0].finish_reason)
                    assistant_msg = msg.model_dump(exclude_none=True)
                    # console.print((pformat(str(assistant_msg))))
                    if msg.tool_calls:
                        with self._state_lock:
                            self.messages.append(assistant_msg)
                        current_messages.append(assistant_msg)
                        self.api.usage.record(response.usage, turn=len(self.messages))
                        console.print(f"[dim]{self.api.usage.summary()}[/dim]")

                        tool_results = self._get_tool_results(msg.tool_calls)
                        if not tool_results:
                            continue

                        with self._state_lock:
                            self.messages.extend(tool_results)
                        current_messages.extend(tool_results)

                        if self.api.usage.context_pct >= 90.0:
                            # Emergency trim
                            self._trim_context()
                            console.rule(f"[darkred]Emergency Trim - {self.api.usage.summary()}[darkred]")
                            current_messages.append({"role": "system", "content": "Emergency trim context."})
                            with self._state_lock:
                                current_messages = list(self.messages)
                                current_messages.append({
                                    "role": "system",
                                    "content": "Your conversation history has been compressed. "
                                            "Continue from the supplied historical summary."
                                })

                        # DEBUG: line below
                        #console.print(f"CURRENT MESSAGES: {pformat(str(current_messages))}")
                        elapsed = time.time() - start_time
                        continue

                    content = msg.content or ""
                    with self._state_lock:
                        self.messages.append({"role": "assistant", "content": content})

                    # Calculate elapsed time
                    elapsed = time.time() - start_time

                    # Check for tool re-enable requests in assistant response
                    # Pattern: /tool enable <tool_name> or /tool request <tool_name>
                    if "/tool" in content:
                        import re
                        # Match /tool enable <name> or /tool request <name>
                        tool_requests = re.findall(r'/tool\s+(?:enable|request)\s+(\w+)', content)
                        if tool_requests:
                            for tool_name in tool_requests:
                                if self.tool_registry.enable_tool_if_not_banned(tool_name):
                                    console.print(f"[green]Re-enabled tool on request: {tool_name}[/green]")
                                else:
                                    console.print(f"[red]Cannot re-enable '{tool_name}': tool is banned or not found[/red]")
                        elif "/tool" in content and not tool_requests:
                            # Legacy: just "/tool" enables all
                            tools_command(self, "on")

                    if content:
                        self._draw_end_rule(True)
                        console.print("\n") # newline, seems hacky
                        console.print(Panel(Markdown(content), title="Assistant"))


                    else:
                        console.print("[bold red]Assistant: (No response)[/bold red]")
                    with self._state_lock:
                        self.no_reply = False

                    # Only print time if it exceeds 5 seconds
                    if elapsed > 5.0:
                        console.print(f"[dim]⏱️  Turn completed in {elapsed:.2f}s[/dim]")
                        # self.redraw_prompt = True
                        self.no_reply = False
                        self._draw_statusbar()
                        # Hack:
                        prefix = self.get_input_prompt_prefix()
                        console.print(prefix, end="")


                    self._enqueue_profile_snapshot(user_input, content)
                    self.agent_active = False
                    return content
                except Exception as e:
                    self.no_reply = False
                    if "request exceeds the context window" in str(e):
                        self._trim_context()
                        console.rule(f"[darkred]Emergency Trim - {self.api.usage.summary()}[darkred]")
                        current_messages.append({"role": "system", "content": "Emergency trim context."})
                        with self._state_lock:
                            current_messages = list(self.messages)
                            current_messages.append({
                                "role": "system",
                                "content": "Your conversation history has been compressed. "
                                        "Continue from the supplied historical summary."
                            })
                        continue
                    if isinstance(e, InternalServerError):
                        return f"API Error: {e}"
                    elapsed = time.time() - start_time
                    if elapsed > SEND_TIMEOUT:
                        self.agent_active = False
                        raise APIError(f"Response timed out after {elapsed:.2f}s")
                    if not self._handle_api_error(e):

                        self.agent_active = False
                        return f"API Error: {e}"



    def _handle_api_error(self, e: Exception) -> bool:
        assert self.api
        with self._state_lock:
            if self.current_bg_task == None or self.status == "stop":
                return False
        try:
            action, delay = classify_api_error(e)
        except Exception:
            action, delay = Action.ABORT, 0.0
        if action in (Action.RETRY, Action.BACKOFF):
            logger.warning(f"API error {action}: {e}. Waiting {delay}s...")
            try:
                if (e.response.status_code == 500 # type: ignore
                    and "Failed to parse tool call arguments as JSON" in str(e)):
                    self.notools = True
                    with self._state_lock:
                        self.messages.append(
                            {"role": "system", "content": "disabled tool calls. re-enable with /tools"}
                            )
                        tools_command(self, "reload")
                time.sleep(delay)
            except KeyboardInterrupt:
                return False
            except Exception:
                pass
            return True
        logger.error(f"Fatal API error: {e}")
        if "exceeds the available context size" in str(e):
            try:
                logger.debug(f"Messages: %d, %s", len(self.messages), [s for s in self.messages])
            except TypeError:
                logger.debug(f"Messages: %d, %s", len(self.messages), [str((s.get('role'), s.get('content'))) for s in self.messages])
            n_ctx = getattr(e, "body", {}).get("error", {}).get("n_ctx")
            if n_ctx:
                self.api.update_context_limit(n_ctx)
            else:
                new_limit = self.api.context_limit
                old_limit = self.api.context_limit
                if old_limit > 8192:
                    new_limit = int(self.api.context_limit / 1.1)
                    self.api.update_context_limit(int(new_limit))
                logger.warning(f"Failed to update context limit, reduced context from {old_limit} to {new_limit}.")
            self._trim_context(bool(self.api.context_limit*0.8))
            self._consolidate_profile()

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

    def _consolidate_profile(self) -> None:
        # test if consolidation is needed
        if not self.profile_manager.needs_consolidation():
            console.print("[faded]Profile already consolidated.[/faded]")
            return
        self.prompt_gen.reload_profiles()
        consolidation_prompt = self.prompt_gen.generate_prompt("profile_consolidation")
        self._apply_profile_update("", "", prompt = consolidation_prompt)
        console.print("[faded]Profile consolidated.[/faded]")


    # --- Job management -----------------------------------------------------------

    def _render_tool_list(self) -> str:
        return "\n".join(
            f"- `{s['function']['name']}` — {s['function']['description']}"
            for s in self.tool_schemas
    )



    def _load_commands(self) -> Tuple[Dict[str, Callable], Dict[str, Dict[str, Any]]]:
         commands, command_definitions = load_commands()
         # can modify commands here.

         return commands, command_definitions

    def _drain_pending_inputs(self) -> str | None:
        """Pop everything queued so far and join into one input."""
        parts: list[str] = []
        while True:
            try:
                parts.append(self.pending_user_inputs.get_nowait())
            except queue.Empty:
                break
        # Also pull any due Message objects from input_queue
        now = time.time()
        deferred = []
        while True:
            try:
                item = self.input_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, Message) and item.send_time and item.send_time <= now:
                parts.append(item.content)
            else:
                deferred.append(item)
        for item in deferred:
            self.input_queue.put(item)
        return "\n".join(p for p in parts if p) or None

    def _poll_background_tasks(self) -> None:
        """Non-blocking check for background send completion/output."""
        proc = self.current_bg_task
        if not proc:
            return

        for msg in proc.get_pending_output():
            console.print(f"[dim]⚙️  {msg}[/dim]")

        # IMPORTANT: is_running is a property, not a method.
        if proc.is_running:
            return

        self.current_bg_task = None
        self.agent_active = False

        if proc.error:
            console.print(f"[bold red]Background task failed: {proc.error}[/bold red]")
        else:
            self._on_send_done(proc.result)

        # If the user typed stuff while the model was busy, start the next turn now.
        try:
            next_input = self._drain_pending_inputs()
            console.print("[dim]Processing queued user input...[/dim]")
            console.print(f'[dim][i]"{next_input}"[/i][/dim]')

            self._start_background_send(next_input)
            return
        except queue.Empty:
            pass

    async def _background_ui_pump(self) -> None:
        while not self._shutdown_done:
            self._check_profile_worker_health()
            self._poll_background_tasks()
            await asyncio.sleep(0.05)

    def _on_send_done(self, result):
        self.agent_active = False
        try:
            content = result
            # console.print(Panel(Markdown(content), title="Assistant"))
        except Exception as e:
            console.print(f"[bold red]API Error: {e}[/bold red]")
            diagnostics = self.get_diagnostics()
            console.print(Panel(Markdown(str(diagnostics)), title="Diagnostics"))

    def _process_command(self, command, args, params):
        logger.info(("COMMAND:", command, args, params))
        status = self.cmd_dispatcher.dispatch(command, args, params)
        if status:
            # logger.info(f"Command status: {status}")
            if isinstance(status, LoopTask):
                self.loop_task = status
            if isinstance(status, Message):

            return status

    def _status_fields(self) -> dict:
        """Single source of truth for status display. Never raises, never mutates."""
        api    = getattr(self, "api", None)
        client = getattr(self, "client", None)
        usage  = getattr(api, "usage", None)
        return {
            "model":    getattr(self, "model", None) or "(unknown)",
            "base_url": str(getattr(client, "base_url", "") or "(unset)"),
            "n_ctx":    getattr(api, "context_limit", None) or "(unset)",
            "backend":  getattr(self, "backend", None) or "(unset)",
            "pct":      getattr(usage, "context_pct", 0.0) or 0.0,
        }

    def get_input_prompt_prefix(self):

        agent = "👣" if self.agent_active else ""
        looptask= "🔁" if self.loop_task else ""
        prefix = f"({agent}{looptask})"
        if len(prefix) == 2: prefix=""
        return f"{prefix}User > "
    async def get_user_prompt(self, prompt_session):
        try:

            input_prompt = self.get_input_prompt_prefix()
            if prompt_session is not None:
                user_input = await prompt_session.prompt_async(
                    input_prompt,
                    bottom_toolbar=self._toolbar_fragments,
                    style=TOOLBAR_STYLE,
                    refresh_interval=1
                )
            else:
                user_input = input(input_prompt).strip()
            self.user_messages.append(user_input)
        except EOFError:
            return None
        except KeyboardInterrupt:
            return "keyboard_interrupt"
        return user_input

    def _draw_statusbar(self):
        if self.no_reply:
            return
        f = self._status_fields()
        console.rule(f"[turquoise4]{f['model']}|{f['base_url']}|{f['n_ctx']}|{f['backend']}[/turquoise4]")
        self.no_reply = True


    def run(self) -> None:
        asyncio.run(self._run())


    def process_slash_commands(self, user_input) -> (bool, Any):
        def _is_command(command):
            return command in self.cmd_dispatcher.commands

        def _alias_script(alias):
            if isinstance(alias, Script):
                result = alias(self, args, params)
                if result:
                    console.print(result)
                return (True, result)
            return (False, None)

        if user_input.startswith("/"):
            command, args, params, errors = parse_command(user_input) # type: ignore
            if _is_command(command):
                result = self._process_command(command, args, params)
                return (True, result)
            elif command in self.aliases.keys():
                alias = self.aliases.get(command,"")
                is_alias, result = _alias_script(alias)
                if is_alias:
                    return (True, result)
                # Let's try to parse it as a final fallback:
                alias_cmd, args, params, errors = parse_command(f"/{alias}") # type: ignore
                logger.info(f"Alias: {command} = {alias_cmd} {args} {params}")
                if _is_command(alias_cmd):
                    result = self._process_command(alias_cmd, args, params)
                    return (True, result)
                console.print(f"Failed to process alias: {alias}")
            else:
                console.print(f"[bold red]Unknown command: {user_input}[/bold red]")
                return (True, None)
        return (False, None)


    async def _run(self):
        try:
            ui_pump = None
            commands, command_definitions = self._load_commands()
            self.cmd_dispatcher = CommandDispatcher(self)
            self.cmd_dispatcher.load(commands, command_definitions)
            self.aliases = {}

            command_help = ",".join(
                f'[bold]/{k}[/bold] {v.get("help", "")}'
                for k, v in command_definitions.items()
                )
            try:
                base_url =self.client.base_url
            except Exception:
                base_url = "(unset)"

            console.rule("[bold green]LLM REPL Started (Profiled V2)[/bold green]")
            console.print(f"Model: [bold]{self.model}[/bold] | Base URL: [bold]{base_url}[/bold]")
            console.print(f"Commands: {command_help}")

            self.loop_task = None
            self.agent_active = False
            prompt_session = PromptSession(history=FileHistory(str(history_path)), refresh_interval=1)
            result = ""
            self.user_messages=[]

            # UI pump handles async tasks
            ui_pump = asyncio.create_task(self._background_ui_pump())

            with patch_stdout(True):
                self.no_reply=False
                while True:
                    try:
                        # live update model
                        #self.no_reply = False
                        if not (self.loop_task and self.agent_active):
                            self._draw_statusbar()

                        # Get User Input
                        user_input = ""

                        if isinstance(self.loop_task, SimpleLoopTask):
                            if self.agent_active:
                                # LLM is busy. Wait a bit and let the loop iterate.
                                # DO NOT call get_next_input() here, or we pop content prematurely.
                                await asyncio.sleep(0.5)
                            # Priority 2: Loop task has more inputs
                            if isinstance(self.loop_task, SimpleLoopTask) and not self.agent_active:
                                next_input = self.loop_task.get_next_input() or ""
                                # tick
                                if next_input:
                                    if not self._start_background_send(next_input):
                                        self.loop_task.stop()
                                        self.loop_task.cleanup()
                                        console.print("[yellow]Loop halted: REPL is in 'stop' state.[/yellow]")
                                    continue

                        if not user_input and not self.agent_active:
                            try:
                                user_input = self.pending_user_inputs.get_nowait()
                                console.print("[dim]Processing queued input...[/dim]")
                            except queue.Empty:
                                pass

                        if not user_input or user_input == "":
                            if not self.loop_task:
                                self.status="run"
                                user_input = await self.get_user_prompt(prompt_session)
                                    # logger.warning(user_input)
                                if user_input in ["keyboard_interrupt", "stop", "quit"]:
                                    self._draw_end_rule()
                                    raise KeyboardInterrupt("Interrupted by User")


                        messages = self.user_messages
                        self.user_messages = []

                        if user_input in messages:
                            messages.remove(user_input)
                        for msg in messages:
                            if isinstance(msg, str):
                                user_input += msg


                        if not user_input:
                            # Existing agent sessions are still active. Or not. Regardless
                            continue

                        # Got userinput, parse
                        status, result = self.process_slash_commands(user_input)
                        if status == True:
                            if result == "quit": # was slashcommand, do not pass go
                                break
                            console.print(result)
                            continue
                            user_input = ""



                        # Pass to LLM
                        if not self.agent_active:
                            self._start_background_send(user_input)
                        else:
                            # Getting false positive here
                            self.pending_user_inputs.put(user_input)
                            console.print("[dim]Queued input; assistant is still processing.[/dim]")
                    except EOFError:
                        console.print("[bold red]Goodbye![/bold red]")
                        break
                    except KeyboardInterrupt as ke:
                        self.no_reply = False
                        if self.loop_task:
                            try:
                                self.loop_task.stop()
                                logger.warning("Loop task interrupted!")
                                continue
                            except Exception as e:
                                logger.error(f"Error stopping loop task: {e}")
                                self.loop_task = None
                            continue # avoid exit _once_
                        if self.agent_active and self.current_bg_task:
                            with self._state_lock:
                                self.status = "stop"
                            logger.warning("Interrupted by user")
                            with self._state_lock:
                                self.messages.append({"role": "user", "content": "stop"})
                            if self.current_bg_task:
                                self.current_bg_task.stop()
                                self.current_bg_task = None
                            console.print("[dim]Background task interrupted.[/dim]")
                            continue
                        console.print("\n[bold red]Goodbye![/bold red]")
                        break
                    except Exception as e:
                        self.agent_active = False
                        logger.exception(f"Unexpected error during REPL loop: {e}")
                        console.print(f"[bold red]Unexpected error: {e}[/bold red]")
                        self.no_reply = False
        finally:
            if ui_pump:
                ui_pump.cancel()
                try:
                    await ui_pump
                except asyncio.CancelledError:
                    pass

            self.shutdown()


    def _apply_profile_update(self, user_input: str, assistant_response: str="", prompt="") -> None:
        try:
            profile_data = self.profile_manager.profile_data

            # Inject all possible placeholders
            prompt = prompt.replace("{profile_json}", json.dumps(profile_data, indent=2)) \
                           .replace("{user_input}", user_input) \
                           .replace("{assistant_response}", assistant_response)

            if not prompt.strip():
                logger.error("Profile update prompt is empty after substitution!")
                return

            response = self._request_chat_completion(
                [{"role": "system", "content": "You are a helpful assistant that outputs ONLY valid JSON representing the user profile."},
                 {"role": "user", "content": prompt}],
                tools=None,
                tool_choice=None,
            )
            content = response.choices[0].message.content

            # DEBUG: See what the LLM actually returned
            # logger.debug(f"LLM raw profile response: {content[:100]}...")

            updated_json = None
            if content:
                updated_json = robust_json_extract(content)

            if updated_json is None:
                logger.error(f"Profile worker returned invalid JSON. Raw content: {content}")
                raise ValueError("Profile worker returned invalid JSON.")

            with self._state_lock:
                self.profile_manager.set_profile_data(updated_json)
                self.system_prompt = self._build_system_prompt()
                if self.messages and _role(self.messages[0]) == "system":
                    self.messages[0] = {"role": "system", "content": self.system_prompt}
            logger.info("✅ User profile updated by worker.")

        except Exception as e:
            logger.error(f"Profile update failed: {e}")


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
                    "backend": {
                        "type": "string",
                        "description": "Backend to use. options:[ollama, mistral, llamacpp, koboldcpp]",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Port to use for the agent.",
                    }
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
    {
        "type": "function",
        "function": {
            "name": "stop_loop",
            "description": ("You may stop the autonomous session using stop_loop "
                            "when the task is complete or when a genuine blocker "
                            "prevents further progress. Do not use it merely "
                            "because you have completed a phase or have nothing "
                            "immediately obvious to do."),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


def create_tool_registry(repl: LLMRepl) -> ToolRegistry:
    """Build a per-REPL registry from existing tool definitions and callables."""

    conf = None
    # Load allowed paths from environment
    if not os.getenv("ALLOWED_PATHS"):
        # Load from yaml
        conf_path = Path.cwd() / "tool_config.yaml"
        if conf_path.is_file():
            with open(conf_path, "r", encoding="utf-8") as f:
                conf = yaml.safe_load(f) or {}
            if conf:
                allowed_paths = list(conf.get("allowed_paths", []))
                if allowed_paths:
                    os.environ["ALLOWED_PATHS"] = ",".join(allowed_paths)
            else:
                logger.warning(f"No allowed paths found in {conf_path}.")
        else:
            logger.warning(f"No tool_config.yaml found in {Path.cwd()}.")
            os.environ["ALLOWED_PATHS"] = str(Path.cwd().resolve())
            # Path(conf_path).touch() # Let's not, for now.
            conf = {}

    registry = ToolRegistry()

    # The definitions in agent_tools are the source of truth for the
    # core, internet, tmux, and context tools.
    definitions = list(BASE_TOOL_SCHEMAS)

    logger.debug("Definitions: %s", definitions)



    _jobmgr = JobManager(repl)

    def stop_loop():
        task = repl.loop_task
        if task is None:
            return "No loop task running."
        task.stop()
        repl.loop_task = None
        return "Loop task stopped."

    # Bind REPL-specific functions to this instance.
    repl_functions = {
        "dispatch_agent": _jobmgr._dispatch_agent_job,
        "check_job": _jobmgr._check_job,
        "list_jobs": _jobmgr._list_jobs,
        "stop_loop": stop_loop,
    }
    definitions.extend(REPL_TOOL_DEFINITIONS)

    # if platform.system() == "Windows":
    #     logger.warning("REPL tool registry: Windows detected; disabling 'dispatch_agent' tool.")
    #     for fn in ["dispatch_agent", "check_job", "list_jobs"]:
    #         repl_functions.pop(fn, None)
    #     #definitions = [d for d in definitions if d.get("function", {}).get("name") != "dispatch_agent"]
    if conf:
        if conf.get("enabled_tools"):
            definitions = [d for d in definitions if d.get("function", {}).get("name") in conf["enabled_tools"]]

    # Use the existing implementation map; the definitions supply schemas.
    implementations = dict(BASE_TOOL_MAP or {})
    implementations.update(INTERNET_TOOL_MAP or {})
    implementations.update(repl_functions)

    registered = set()

    assert len(definitions) > 0, "No tool definitions found for REPL registry."

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
        registry.disable_tool("stop_loop")

    return registry


# --- Entry point ------------------------------------------------------------------
def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run LLM REPL")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help="LLM backend to use")
    parser.add_argument("--port", default=9931, type=int, help="Port to use")
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    try:
        repl = LLMRepl()
        repl._init(args.backend, args.port)
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

print(f"__name__ = {__name__!r}")
print(f"__file__ = {__file__!r}")


if __name__ == "__main__":
    import tools
    # logger.debug(BASE_TOOL_SCHEMAS)
    # logger.debug(BASE_TOOL_MAP)
    print("Starting...")
    raise SystemExit(main())
