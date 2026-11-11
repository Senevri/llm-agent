#!/usr/local/bin/python

import os
import inspect
import sys
import platform
import shlex
import json
import logging
import tempfile
import asyncio
from datetime import timedelta, datetime
import subprocess
import secrets
import textwrap
import time
import queue
import threading
import atexit
import yaml
import urllib
import re
import uuid
import shutil
from pprint import pformat
from httpx2 import ConnectError, HTTPError
#from requests.exceptions import HTTPError
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Any, List, Callable, NamedTuple, Optional, Union, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial

from openai import OpenAI, APIConnectionError, APIError as AE, InternalServerError
from openai_error_handling import classify_api_error, Action


from prompt_generator import PromptGenerator, find_prompt_dir
from agent_dispatcher import AgentDispatcher, Status as AgentStatus
from backend import LLMBackend, BACKEND_MAP
from loop_task import LoopTask, SimpleLoopTask, loop
from command_dispatcher import CommandDispatcher, parse_command
from user_profile_manager import UserProfileManager, ContextSnapshot
from log_queue import LogQueueHandler, LogQueueListener
from background_util import run_in_background, BackgroundProcess

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

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
    robust_json_extract, balanced_braces_extract, _role)
from profileworker import ProfileWorker

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

# --- Setup Logging ------------------------------------------------------------

# --- Setup Logging (Unified & Thread-Safe) ------------------------------------
from custom_logger import setup_logging

# 1. Initialize the robust wrapped logger (handles file + basic stream)
logger = setup_logging("LLMReplV3", level="DEBUG" if os.getenv("DEBUG") else "WARNING", log_dir=Path.cwd() / "logs")

# 2. OPTIONAL BUT RECOMMENDED: Remove the standard StreamHandler to prevent
# duplicate console prints, since the Queue Listener will handle console output safely.
for h in list(logger.handlers):
    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
        logger.removeHandler(h)

# 3. Add the thread-safe queue handler for console output (prevents prompt_toolkit garbling)
_log_queue = queue.Queue()
_log_handler = LogQueueHandler(_log_queue)
_log_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
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

try:
    from tools.internet_tools import (
        INTERNET_TOOL_DEFINITION_MAP, INTERNET_TOOL_MAP
    )
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
    BASE_TOOL_MAP = {}
    BASE_TOOL_SCHEMAS = []

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




# --- REPL commands --------------------------------------------------------------

def load_commands():

    command_definitions = {
        "quit": {
            "aliases":  ["quit", "q", "exit", "bye"],
            "help": "",
        },
        "clear": {
            "help": "reset"
        },
        "sys": {
            "help": "display current system prompt or <prompt> set system prompt",
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
        },
        "todo": {
            "help": "<add|list|rm> add/list/remove tasks",
        },
        "read": {
            "help": "<file> read file without sending it to LLM",
        },
        "load": {
            "help": "<file> send a file to llm.",
        },
        "tools": {
            "help": "list available tools",
        },
        "config": {
            "help": "<save|load> save or load config",
        },
        "shell": {
            "help": "<command> execute shell command",
        },
        "repl": {
            "help": "execute repl method",
        },
        "status": {
            "help": "show status",
        },
        "alias": {
            "help": "<alias> <command> <args> set alias | <alias set <alias> <python|bash> <script>> | <alias set <alias> <command string>>",
        }
    }


    # ---

    commands = {
        "quit": quit_command,
        "clear": clear_command,
        "sys": system_prompt_command,
        "model": model_command,
        "history": history_command,
        "profile": profile_command,
        "role": role_command,
        "backend": backend_command,
        "help" : help,
        "loop": loop,
        "read": read_command,
        "load": load_command,
        "tools": tools_command,
        "todo": task_command,
        "config": config_command,
        "shell": shell_command,
        "repl": repl_command,
        "status": status_command,
        "alias": alias_command

    }

    # let's get unique commoands:
    return commands, command_definitions


# --- Commands for CommandDispatcher -------------------------------------------------------------

from tools.bash_tools import run_bash

class Script:
    def __init__(self, repl, command, script, **kwargs):
        self.repl = repl
        self.command = command
        self.script = script

    def __call__(self, repl, *args, **kwargs):
        #run_bash(self.script)
        if self.command == "python":
            result = self._execute_python(self.script)
        else:
            result = run_bash(self.script)
        return result

    def _execute_python(self, script):
        try:
            code = compile(script, "<alias>", "eval")
        except SyntaxError:
            code = compile(script, "<alias>", "exec")
            exec(code, globals())
            return None
        else:
            print (code, globals())
            return eval(code, globals())

    def __str__(self):
        if len(self.script) > 20:
            return f"Script: ```{self.command}\n{self.script}\n```"
        return f"Script: #{self.command}:{self.script}"

    def __repr__(self):
        return self.__str__()

def alias_command(repl, *args, **kwargs):
    if len(args) < 2:
        # note: Print has implicit newlines
        console.print(f"[blue]Current aliases[/blue]:")
        [console.print(f'/{k}: {v}') for k, v in repl.aliases.items()]
        return
    if len(args) > 2:
        if args[0] == "set":
            with repl._state_lock:
                if args[2] in ["python", "bash"]:
                    repl.aliases[args[1]] = Script(repl, args[2], " ".join(args[3:]).strip())
                if args[2] == "alias":
                    return "cannot alias alias"
                else:
                    repl.aliases[args[1]] = f"{' '.join(args[2:])}".strip()
        if args[0] == "rm":
            if args[1] in repl.aliases:
                repl.aliases.pop(args[1])
            return "removed alias"

    if args[1] in repl.cmd_dispatcher.commands:
        repl.cmd_dispatcher.register(args[0], args[1])
        repl.aliases[args[0]] = args[1]
        return f"registered new alias for /{args[0]}: {args[1]}"

    console.print(f"[yellow]Alias {args[1]} set to {args[2]}[/yellow]")

def clear_command(repl, *args, **kwargs):
    with repl._state_lock:
        repl.messages = [
            {"role": "system", "content": repl.system_prompt}
        ]
    console.print("[yellow]Conversation history cleared.[/yellow]")

def status_command(repl, *args, **kwargs):
    # TODO: other status here?
    if hasattr(repl, 'current_bg_task') and repl.current_bg_task:
        status = "🟢 Running" if repl.current_bg_task.is_running else "🏁 Finished"
        console.print(f"[bold]Background Task Status:[/bold] {status}")

        # Force a drain of the queue to show history
        outputs = repl.current_bg_task.get_pending_output()
        if outputs:
            console.print("[dim]--- Recent Output ---[/dim]")
            for msg in outputs:
                console.print(f"[dim]{msg}[/dim]")
    else:
        console.print("[faded]No background tasks currently running.[/faded]")
    console.print(f"[faded]{repl.api.usage.summary()}[/faded]")

def repl_command(repl, *args, **kwargs):
    def _parse_attr(attr):
        if "." in attr:
            class_chain = attr.split(".")
            attr = getattr(repl, class_chain[0])
            for c in class_chain[1:]:
                attr = getattr(attr, c)
        else:
            attr = getattr(repl, attr)
        return attr
    if len(args) == 0:
        if len(kwargs)>0:
            for k, v in kwargs.items():
                attr = _parse_attr(k)
                if v in ["True", "False"]:
                    v = True if v == "True" else False
                if attr:
                    msg = f"Setting {k} to {v}"
                    setattr(attr, k, v)
                    logger.info(msg)
                    console.print(f"[yellow]{msg}[/yellow]")
                    attr = v
        return
    if args[0] == "help":
        if len(args) > 1:
            attr = getattr(repl, args[1])
            console.print(inspect.signature(attr))
            console.print(inspect.getdoc(attr))
        console.print("/repl show displays repl dir\n/repl help <method> displays help for method")
        return
    attr = _parse_attr(args[0])

    if attr == None:
        console.print("[red]Command not found.[/red]")
        return attr
    if callable(attr):
        #result = getattr(repl, args[0])(*args[1:], **kwargs)
        repl_args = list(args[1:])
        result = attr(*repl_args, **kwargs)
    else:
        if hasattr(attr, "__dict__"):
            attr = vars(attr)
        result = attr
    # logger.debug(result)
    return result


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
    _, command_definitions = load_commands()
    def get_aliases(v):
        return  (
            f" (aliases: {', '.join(v['aliases'])})"
            if v.get("aliases") else ""
            )

    cmd_help = "\n".join([f"    /{k}: {v['help'] or get_aliases(v)}" for k, v in command_definitions.items()])
    help_text = textwrap.dedent(f"""
        Commands:
            /help - show this help
            /backend <backend> port=<port> model=<model> - switch backend
        """)
    console.print(help_text + cmd_help)

def system_prompt_command(repl, *args, **kwargs):
    if len(args) < 1:
        console.print(f"[blue]Current system prompt[/blue]: {repl.system_prompt}")
        return
    with repl._state_lock:
        repl.base_system_prompt = args[0].strip()
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    console.print("[yellow]System prompt updated.[/yellow]")

def backend_command(repl, *args, **kwargs):
    try:
        old_backend = [repl.backend, repl.api.port, repl.api.model, repl.client]
    except AttributeError:
        old_backend = [repl.backend, None, None, None]

    if len(args) < 1:
        console.print(f"availabe backends: {', '.join(BACKEND_MAP.keys())} (default: {repl.backend})")
        return
    with repl._state_lock:
        if args[0] not in BACKEND_MAP.keys():
            console.print(f"[red]Backend {args} not found in {BACKEND_MAP.keys()}[/red]")
            return
        repl.backend = args[0]
        try:
            api = LLMBackend(backend=repl.backend)
            api.port = kwargs.get("port", api.port)
            api.model = kwargs.get("model", api.model)
            api.base_url = kwargs.get("base_url", api.base_url)
            repl.client, repl.model = api.get_client()
            repl.api = api
        except (ConnectError, HTTPError) as e:
            console.print(f"[red]Failed to switch backend: {e}[/red]")
            repl.backend = old_backend[0]
            repl.api.port, repl.api.model, repl.client = old_backend[1:]
            return

        repl.prompt_gen.reload_profiles()
        repl.base_system_prompt = repl.prompt_gen.generate_prompt(repl.current_role)
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    # save conf
    save_config(repl)
    console.print(f"[yellow]Backend switched to: {repl.backend}[/yellow]")

def tools_command(repl, *args, **kwargs):
    if "reload" in args:
        repl.skills_manager.discover_skills()
        repl.tool_registry = create_tool_registry(repl)
        console.print("[yellow]Tools reloaded.[/yellow]")
        return
    elif "off" in args:
        repl.notools = True
        console.print("[yellow]Tools disabled.[/yellow]")
        return
    elif "on" in args:
        repl.notools = False
        console.print("[yellow]Tools enabled.[/yellow]")
        return
    elif args and len(args) > 1 and "allow" == args[0]:
        repl.tool_registry.disable_tool("*")
        for arg in args[1:]:
            repl.tool_registry.allow_tool(arg)
        return

    # console.print("[yellow]Available skills:[/yellow]")
    # console.print(repl.skills_manager.get_catalog_summary())
    # for skill_id, meta in repl.skills_manager.catalog.items() or {}:
    #     console.print(f"  - {meta.name}: {meta.description}")
    console.print("[yellow]Available tools:[/yellow]")
    console.print(f' - {", ".join(repl.tool_registry.list_tools())}')
    console.print("[yellow]Disabled tools:[/yellow]")
    console.print(f' - {", ".join(repl.tool_registry._disabled_tools)}')


def task_command(repl, *args, **kwargs):
    tasks: dict = repl.tasks

    # Todo: Switch task color by state?
    if "rm" in args and "idx" in kwargs:
        repl.tasks.pop(int(kwargs["idx"]))
        console.print("[yellow]Task removed.[/yellow]")
    elif "rm" in args and "all" in args:
        repl.tasks = {}
        console.print("[yellow]All tasks removed.[/yellow]")
    elif len(args) == 0 and "idx" in kwargs:
        console.print(f"[green]Task {kwargs['idx']}[/green]: {tasks.get(int(kwargs['idx']))}")
    elif len(args) > 1:
        task_text = " ".join(args)
        task_id = max(repl.tasks, default=-1) + 1
        repl.tasks[task_id] = dict(
            {
                "id": task_id,
                "task": task_text,
                "params": kwargs,
                "status": kwargs.get("status", "pending"),
            }
        )
        console.print(f"[green]Task {task_text[:40]}[...] added.[/green]")
    else:
        console.print("[yellow]Available tasks:[/yellow]")
        for idx, task in repl.tasks.items():
            console.print(f"  - {idx}: {task['task'][:60]}")


def config_command(repl, *args, **kwargs):
    get_config_representation(repl)
    if "save" in args:
        save_config(repl)
        console.print("[yellow]Config saved.[/yellow]")
        return
    elif "load" in args:
        load_config(repl)
        console.print("[yellow]Config loaded.[/yellow]")
        return
    elif "set" in args:
        for k, v in kwargs.items():
            if k in ["backend", "port", "model", "base_url"]:
                repl.api.__dict__[k] = v
            if k in ["n_ctx"]:
                repl.api.update_context_limit(int(v))
                repl._trim_context(int(v))
            repl.tasks = v if k == "todos" else repl.tasks
    else:
        console.print("[yellow]Config:[/yellow]")
        yaml_str = yaml.dump(repl.config).replace("[", "\[").replace("]", "\]")
        console.print(Markdown(f"```yaml\n{yaml_str}\n```"))

def get_config_representation(repl):
    repl_representation = {
        k:v
        for k, v in repl.__dict__.items()
        if not k.startswith("_")
        and k in [
            "backend",
            "port",
            "model",
            "base_url",
            "current_role",
            "tasks",
            ]
    }
    if aliases := getattr(repl, "aliases"):
        repl_representation["aliases"] = {}

        for k, v in repl.__dict__.get("aliases", {}).items():
            if k.startswith("_"):
                continue
            repl_representation["aliases"] = {
                k: f"{v.command} {v.script}" if isinstance(v, Script) else v
                for k, v in aliases.items()
            }

    repl_representation["api"] = {
        k:v for k, v in repl.api.__dict__.items()
        if not k.startswith("_") and k in
        [
            "backend",
            "port",
            "model",
            "base_url",
            ]
        }
    repl.config = repl_representation
    return repl_representation
def save_config(repl, *args, **kwargs):
    repl_representation = get_config_representation(repl)

    # console.print(Markdown(f"```yaml\n{yaml.dump(repl_representation)}\n```"))
    with open(Path.cwd() / "llm_repl.yaml", "w") as f:
        yaml.dump(repl_representation, f)

def load_config(repl, *args, **kwargs):
    conf_path = Path(Path.cwd() / "llm_repl.yaml")
    conf = {}
    if conf_path.is_file():
        with open(conf_path, "r") as f:
            conf = yaml.safe_load(f) or {}
    repl.config = conf
    ports = [
        repl.config.get("port", ""),
        repl.config.get("api", {}).get("port", ""),
        ]
    for port in ports:
        logger.info(f"Config port: {port}")
        if port == "auto" or not str(port).isnumeric():
            repl.config["port"] = None
            repl.config.get("api", {})["port"] = None
            pass

    if conf:
        for k, v in conf.items():
            if k == "aliases":
                continue
            repl.__dict__[k] = v if v is not None else repl.__dict__.get(k, None)
    try:
        repl.api = LLMBackend(backend=conf.get("backend", repl.backend))
    except Exception as e:
        console.print(f"[red]Failed to switch backend: {e}[/red]")
        return
    # validate some values

    repl.aliases = {}
    for k, v in conf.get("aliases", {}).items():
        if isinstance(v, dict) and "command" in v and "script" in v:
            cmd, script = list(v.items())[0]
            repl.aliases[k] = Script(repl, cmd, script)
        else:
            repl.aliases[k] = v
    if not os.getenv("DEBUG", "false").lower() == "true":
        repl.api.logger.setLevel(logger.level)
    repl.backend = repl.api.backend
    repl.current_role = conf.get("role", repl.current_role)
    return repl.api



def history_command(repl, *args, **kwargs):
    table = Table(title="Conversation History")
    table.add_column("Role", style="cyan")
    table.add_column("Content", style="white")
    with repl._state_lock:
        snapshot = list(repl.messages)
    for m in snapshot:
        role = _role(m)
        content = m.get("content") if isinstance(m, dict) else (getattr(m, "content", "") or "")
        content = str(content or "")
        if len(content) > 100:
            content = content[:100] + "..."
        table.add_row(role, content)
    console.print(table)
    if "save" in args:
        repl.save_conversation_history()

def role_command(repl, *args, **kwargs):
    with repl._state_lock:
        repl.current_role = args[0]
        repl.prompt_gen.reload_profiles()
        repl.base_system_prompt = repl.prompt_gen.generate_prompt(repl.current_role)
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    console.print(f"[yellow]Role switched to: {repl.current_role}[/yellow]")

def model_command(repl, *args, **kwargs):
    if len(args) < 1:
        console.print(f"availabe models: {', '.join(repl.api.endpoint.list_models())} (default: {repl.model})")
        return
    repl.model = args[0].strip()
    repl.api.model = repl.model

    console.print(f"[yellow]Model switched to: {repl.model}[/yellow]")

def _make_fence(contents: str) -> str:
    fences = re.findall(r"`+", contents)
    longest = max((len(f) for f in fences), default=2)
    return "`" * max(3, longest + 1)

def _read_file(fname: str) -> str:
    try:
        if Path(fname).is_file():
            with open(fname, "r") as f:
                contents = f.read()
                return contents
    except Exception as e:
        console.print(f"[red]Failed to read file: {e}[/red]")

def load_command(repl, *args, **kwargs):
    fname = args[0].strip()
    contents = _read_file(fname)
    if not contents:
        return

    fence = _make_fence(contents)
    message = f"Contents of {fname}:\n{fence}\n{contents}\n{fence}\n"
    console.print(message)

    # Fire it to the background queue instead of blocking
    repl.pending_user_inputs.put(message)
    if not repl.agent_active:
        repl._start_background_send(message)
def read_command(repl, *args, **kwargs):
    if len(args) < 1:
        cwd = Path.cwd()
        console.print("current directory: " + str(cwd))
        files = '\n\t'.join([str(p) for p in cwd.glob('*')])
        console.print(f"available files: \n{files}")
        return
    fname = args[0].strip()
    contents = _read_file(fname)
    if contents:
        #console.print(f"Contents of {fname}:\n{fence}\n{contents}\n{fence}")
        console.print(contents) # raw output

def shell_command(repl, *args, **kwargs):
    # Join the args back into a single string so the user can use shell operators
    command_str = " ".join(args)
    console.print(f"[dim]Executing: {command_str}[/dim]")

    # Use the robust _run_bash function we refined
    result = run_bash(command_str, cwd=str(WORKSPACE_DIR))

    console.print(result)

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
        self.dispatcher=None
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

        with _active_repls_lock:
            _active_repls += 1


    def init(
            self, repl_be=os.getenv("LLM_REPL_BASE_URL", "http://localhost"),
            port=os.getenv("LLM_REPL_PORT", 8080),
            model=None
            ):

        self.config["backend"] = os.getenv("LLM_REPL_BACKEND", repl_be)
        self.config["port"] = port

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
        self.worker = ProfileWorker(self, self.profile_queue)


        self.worker.start()

        logger.info(
            "Registered %d tools: %s",
            len(self.tool_schemas),
            self.tool_registry.list_tools(),
        )
        logger.info("Discovered skills: %s", ", ".join(self.skills_manager.catalog.keys()))

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

    def show(self):
        console.print(self.get_diagnostics())
        console.print(dir(self))

    def _check_profile_worker_health(self):
        if not self.worker.is_alive():
            logger.error("Profile worker thread is DEAD! Restarting...")
            self.worker = ProfileWorker(self, self.profile_queue)
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
        if hasattr(self, 'dispatcher') and self.dispatcher:
            self.dispatcher.shutdown(stop_owned_jobs=True)

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
                    content = self.ai_compress(sections[1:-1], max_tokens=self.api.context_limit//2)

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

    def ai_compress(self, sections, max_tokens=2000):
        task_message = [
            {"role": "system",
             "content": f"You are a helpful assistant. Provide a concise, condensed version of the prompt below. Aim for maximum of {max_tokens} tokens."},
            {"role": "user", "content": "\n\n".join(sections[:-1])}]

        response =  self.client.chat.completions.create(
                model=self.model,
                messages=normalize_messages(task_message, self.backend)
            )
        return response.choices[0].message.content


    def _trim_context(self, n_ctx:int=0) -> None:
        # Safe to call with or without holding _state_lock (RLock).
        with self._state_lock:
            orig_size_tokens = estimate_tokens(self.messages)
            orig_size_bytes = len(str(self.messages).encode("utf-8"))

            logger.debug(
                    "Context before trim: messages=%d chars=%d",
                    len(self.messages), orig_size_bytes
                )

            # if (
            #     len(self.messages) <= self.max_context_messages
            #     and orig_size_tokens <= self.api.context_limit*0.8
            #     and not n_ctx
            #     ):
            #     return

            try:
                usage_ratio = self.api.usage.context_pct
                # Let's put a gate on pruning
                if usage_ratio < 0.75:
                    return
            except Exception as e:
                logger.warning(f"Could not get usage ratio: {e}")
                # if (not n_ctx
                # and len(self.messages) < self.max_context_messages
                # and orig_size_tokens < self.api.context_limit*0.8):
                #     return

            self.save_conversation_history()
            keep_count = max(self.max_context_messages - 1, 3)


            tail = self.messages[-keep_count:]
            while tail and _role(tail[0]) == "tool":
                tail = tail[1:]
            sections = []

            # Guesstimate tokens; not exact
            if (n_ctx
                or self.api.usage.last_prompt_tokens > self.api.context_limit*0.80):
                # Average token length = 4
                while (estimate_tokens(tail) > self.api.context_limit*2//3 and len(tail) > 1):
                    sections.append(tail[0])
                    tail = tail[1:]
                    if not tail:
                        break
            compress_target = list(sections)
            logger.debug(f"Compress target: {len(compress_target)} messages, characters={len(str(compress_target))}")

            def format_for_compression(msg: dict) -> str:
                if msg.get("role") == "tool":
                    return f"[TOOL RESULT: {msg.get('name', 'unknown')} (ID: {msg.get('tool_call_id')})]\n{msg.get('content')}"
                return f"{msg['role']}: {msg.get('content', '')}"

            sections = [format_for_compression(c) for c in compress_target]
            content = None
            if sections:
                content = self.ai_compress(sections, max_tokens=self.api.context_limit*1//3)
                logger.info(f"condensed context to {content}")
            if content:
                with open(Path(WORKSPACE_DIR) / "condensed_context.txt", "a+", encoding="utf-8") as f:
                    f.write(content + "\n\n------\n\n")
                content = f"Historical context summary - not a new response: {content}"
                tail = [{"role": "assistant", "content": content}] + tail
            self.messages = [self.messages[0]] + tail
        console.print(f"[dim]Trimmed from {orig_size_bytes} to {len(str(self.messages))}[/dim]")
        console.print(f"[dim]Trimmed: {self.api.usage.summary()}[/dim]")
        token_est = estimate_tokens(self.messages)
        chars = self.check_all_context_use()
        console.print(
            f"[dim]Messages: {len(self.messages)}, characters {chars}, est. tokens: {token_est}[/dim]"
        )

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


                    log_args = str(args)
                    #let's not print all the args...
                    if len(log_args) > 240:
                        log_args = log_args[:249] + "[...]"

                    logger.info("Executing tool %s with %s", name, log_args)
                    logger.debug("full args: %s", args)

                    preview = str(args)

                    if len(preview) > 200:
                        preview = preview[:200] + "..."
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

    def _start_background_send(self, user_input: str) -> None:
        if self.status == "stop":
            return
        self.agent_active = True
        self.current_bg_task = run_in_background(self.send_message)(user_input)

    def _draw_end_rule(self, newline=False):
        # Let's mark that the message was sent
        loop_remains = (f"Loop: {self.loop_task.get_remaining_time()}"
        if self.loop_task else "[dark_cyan]ᓚᘏᗢ[dark_cyan]")
        if newline:
            console.print("\n")
        console.rule(f"{loop_remains}")
        self.no_reply = False



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
                self._draw_end_rule()
                console.print(f"[dim]Thinking...   ({self.check_all_context_use()} bytes)[/dim]")
                if self.status == "stop":
                    self.current_bg_task.stop()
                    return "stopped"
                self.no_reply = False
                if self.api.usage.context_pct >= 80.0 and not warning_sent:
                    # warn llm.
                    warning = self.prompt_gen.generate_prompt(
                        "warning", {
                            "snippets": ["context_size_warning"]
                        },
                        context_pct=self.api.usage.context_pct,
                        remaining_tokens=self.api.usage.remaining_tokens
                        )
                    console.rule(f"[dim]warning - {self.api.usage.summary()}[dim]")
                    current_messages.append({"role": "system", "content": warning})
                    warning_sent = True
                try:
                    # json.dumps(self.tool_schemas) # defensive validation
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
                    if ("/tool" in content):
                        tools_command(self, "on")
                    if content:
                        self._draw_end_rule()
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
                    return content
                except Exception as e:
                    self.no_reply = False
                    if isinstance(e, InternalServerError):
                        return f"API Error: {e}"
                    elapsed = time.time() - start_time
                    if elapsed > SEND_TIMEOUT:
                        raise APIError(f"Response timed out after {elapsed:.2f}s")
                    if not self._handle_api_error(e):
                        return f"API Error: {e}"


    def _handle_api_error(self, e: Exception) -> bool:
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
            logger.debug(len(self.messages), self.messages)
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
            self._trim_context(int(self.api.context_limit*0.8))
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

    def _dispatch_agent_job(
        self,
        task: str,
        profile: str = "software-dev",
        backend: str = "ollama",
        model: Optional[str] = None,
        port: Optional[int] = None,
        max_turns: int = 40,
        timeout: int = 1800,
    ) -> str:
        if (
            not hasattr(self, "dispatcher")
            or not self.dispatcher
        ):
            self.dispatcher = AgentDispatcher(
                agent_dir=str(AGENT_DIR),
                prompt_gen=self.prompt_gen,
            )


        self.dispatcher.backend = backend
        self.dispatcher.model = (
            model
            or os.getenv(f"AGENT_MODEL_{backend.upper()}")
            or os.getenv("AGENT_MODEL")
        )
        self.dispatcher.port = port

        job_id, job = self.dispatcher.dispatch_agent_job(
            task,
            profile=profile,
            max_turns=max_turns,
            timeout=timeout,
        )
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
        if not self.dispatcher:
            return f"Job {job_id} not found."
        try:
            log_text = self.dispatcher.get_job_output(job_id, tail_chars=2000)
            tail = log_text[-2000:]
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
            self._jobs = self.dispatcher.active_jobs or {}

            if not self._jobs:
                return "No jobs dispatched."

            lines = []
            for jid, j in self._jobs.items():
            # use dispatch there is no proc
                status = j["status"]
                if isinstance(j["start"], datetime):
                    j["start"] = j["start"].timestamp()
                elapsed = time.time() - j["start"]
                lines.append(f"{jid}: {status} ({elapsed:.0f}s, profile={j.get('profile', 'unknown')})")
            return "\n".join(lines)

    def _load_commands(self) -> Tuple[Dict[str, Callable], Dict[str, Dict[str, Any]]]:
         commands, command_definitions = load_commands()
         # can modify commands here.

         return commands, command_definitions

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
            next_input = self.pending_user_inputs.get_nowait()
        except queue.Empty:
            return

        console.print("[dim]Starting queued user input...[/dim]")
        console.print(f'[dim][i]"{next_input}"[/i][/dim]')
        self._start_background_send(next_input)

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
            return status

    def get_input_prompt_prefix(self):
        agent = "(👣)" if self.agent_active else ""
        return f"{agent}User > "
    async def get_user_prompt(self, prompt_session):
        try:
            input_prompt = self.get_input_prompt_prefix()
            if prompt_session is not None:
                user_input = await prompt_session.prompt_async(input_prompt)
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
        try:
            self.model = self.api.model
            base_url = self.client.base_url
            n_ctx = self.api.context_limit
        except Exception:
            base_url = "(unset)"
            n_ctx = "(unset)"
        rule_str=f"[turquoise4]{self.model}|{base_url}|{n_ctx}|{self.backend}[/turquoise4]"
        console.rule(rule_str)
        self.no_reply=True



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

            cb = None
            result = ""
            self.user_messages=[]
            ui_pump = asyncio.create_task(self._background_ui_pump())

            with patch_stdout(True):
                self.no_reply=False
                while True:
                    try:
                        # live update model
                        self._draw_statusbar()

                        # Get User Input
                        user_input = ""
                        if isinstance(self.loop_task, SimpleLoopTask):
                            user_input = self.loop_task.get_next_input() or ""
                            if user_input:
                                console.print(f"User(loop) > {user_input}\n")
                                # Fire it and wait for completion
                                self._start_background_send(user_input)
                            else:
                                self.loop_task.cleanup()

                            while self.agent_active:
                                # time.sleep(1)
                                # experimental: wait for user input(async)
                                self._draw_statusbar()
                                _user_input = await self.get_user_prompt(prompt_session)
                                if _user_input in ["keyboard_interrupt", "stop", "quit"]:
                                    self._draw_end_rule()
                                    raise KeyboardInterrupt("Agent Interrupted by User")
                                status, result = self.process_slash_commands(_user_input)
                                if status:
                                    self.user_messages.pop(self.user_messages.index(_user_input))
                                    if result == "quit":
                                        break
                                    if result:
                                        console.print(result)
                                        self.no_reply = False

                                # NOTE: Input went to message queue

                        if not user_input or user_input == "":
                            self.status="run"
                            user_input = await self.get_user_prompt(prompt_session)
                                # logger.warning(user_input)
                            if user_input in ["keyboard_interrupt", "stop", "quit"]:
                                self._draw_end_rule()
                                raise KeyboardInterrupt("Interrupted by User")
                            if user_input in self.user_messages:
                                self.user_messages.pop(self.user_messages.index(user_input))

                        for msg in self.user_messages:
                            if not user_input:
                                user_input = ""
                            if isinstance(msg, str):
                                user_input += msg
                                self.user_messages = []

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


                        # Pass to LLM

                        if not self.agent_active:
                            self._start_background_send(user_input)
                        else:
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
            logger.debug(f"LLM raw profile response: {content[:300]}...")

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

    # Bind REPL-specific functions to this instance.
    repl_functions = {
        "dispatch_agent": lambda **kwargs: repl._dispatch_agent_job(**kwargs),
        "check_job": lambda job_id, **kwargs: repl._check_job(job_id),
        "list_jobs": lambda **kwargs: repl._list_jobs(),
        "stop_loop": lambda **kwargs: repl.loop_task.stop() or "loop task stopped!",
    }

    definitions.extend(REPL_TOOL_DEFINITIONS)

    if platform.system() == "Windows":
        logger.warning("REPL tool registry: Windows detected; disabling 'dispatch_agent' tool.")
        for fn in ["dispatch_agent", "check_job", "list_jobs"]:
            repl_functions.pop(fn, None)
        #definitions = [d for d in definitions if d.get("function", {}).get("name") != "dispatch_agent"]
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





# Job manager facade retaining a simple API without changing LLMRepl internals.
class JobManager:
    def __init__(self, repl: LLMRepl):
        self.repl = repl

    def dispatch(self, task: str, profile: str = "engineering", max_turns: int = 40, timeout: int = 1800, **kwargs) -> str:
        return self.repl._dispatch_agent_job(task, profile=profile, max_turns=max_turns, timeout=timeout, **kwargs)

    def check(self, job_id: str) -> str:
        return self.repl._check_job(job_id)

    def list(self) -> str:
        return self.repl._list_jobs()

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
        repl.init(args.backend, args.port)
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
    import tools
    # logger.debug(BASE_TOOL_SCHEMAS)
    # logger.debug(BASE_TOOL_MAP)

    raise SystemExit(main())
