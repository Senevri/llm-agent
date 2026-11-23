from loop_task import loop
from pathlib import Path
from typing import Optional
import os
import ast
import inspect
import re
import sys
import time
import yaml

import textwrap
import logging


from httpx2 import ConnectError, HTTPError

from tools import WORKSPACE_DIR
from llm_utils import _role, Message
from backend import BACKEND_MAP, LLMBackend
from custom_logger import setup_logging

logger = setup_logging("SlashCommands")


from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
if SCRIPT_DIR not in sys.path:
    sys.path.append(str(SCRIPT_DIR))

try:
    from rich.table import Table
    # from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
except ImportError:
    # actually mock here for now.
    class Table:
        def __init__(self, *args, **kwargs):
            pass
        def add_column(self, *args, **kwargs):
            pass
        def add_row(self, *args, **kwargs):
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

# --- Command helpers ----------------------------------------------------------
def _switch_repl_backend(
    repl,
    backend=None,
    *,
    port=None,
    model=None,
    base_url=None,
) -> LLMBackend:
    backend = backend or repl.backend

    if repl.api:
        repl.api.switch(backend, {
            "port": port,
            "model": model,
            "base_url": base_url
        })
    else:
        api = LLMBackend(
            backend=backend,
            defer_init=True,
            port=port,
        )
        api.port = port or api.port
        api.model = model or api.model
        api.base_url = base_url or api.base_url

    api._get_endpoint()
    api.model = api.endpoint.model
    api.base_url = api.endpoint.base_url.rstrip("/")
    api.port = api.endpoint.port

    client, resolved_model = api.get_client()

    # Commit only after successful initialization.
    repl.api = api
    repl.client = client
    repl.model = resolved_model
    repl.backend = backend

    return api

def alias_command(repl, *args, **kwargs):
    console = repl.ui_console
    if len(args) < 2:
        # note: Print has implicit newlines
        repl.ui_messages.post(f"[blue]Current aliases[/blue]:")
        [repl.ui_messages.post(f'/{k}: {v}') for k, v in repl.aliases.items()]
        return
    if len(args) > 2:
        if args[0] == "set":
            with repl._state_lock:
                if args[2] in ["python", "bash"]:
                    repl.aliases[args[1]] = Script(repl, args[2], " ".join(args[3:]).strip())
                elif args[2] == "alias":
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

    repl.ui_messages.post(f"[yellow]Alias {args[1]} set to {args[2]}[/yellow]") # type: ignore

def clear_command(repl, *args, **kwargs):
    console = repl.ui_console
    with repl._state_lock:
        repl.messages = [
            {"role": "system", "content": repl.system_prompt}
        ]
    repl.ui_messages.post("[yellow]Conversation history cleared.[/yellow]")

def status_command(repl, *args, **kwargs):
    # TODO: other status here?
    repl.no_reply = False
    repl._draw_statusbar(force=True)
    console = repl.ui_console
    if hasattr(repl, 'current_bg_task') and repl.current_bg_task:
        status = "🟢 Running" if repl.current_bg_task.is_running else "🏁 Finished"
        repl.ui_messages.post(f"[bold]Background Task Status:[/bold] {status}")

        # Force a drain of the queue to show history
        outputs = repl.current_bg_task.get_pending_output()
        if outputs:
            repl.ui_messages.post("[dim]--- Recent Output ---[/dim]")
            for msg in outputs:
                repl.ui_messages.post(f"[dim]{msg}[/dim]")
    else:
        repl.ui_messages.post("[faded]No background tasks currently running.[/faded]")
    repl.ui_messages.post(f"[faded]{repl.api.usage.summary()}[/faded]")

# --- attribute-path mechanism: pure, stable, unit-testable -------------------

_PATH_TOKEN = re.compile(r"\s*\.?\s*([A-Za-z_]\w*)|\[\s*(.*?)\s*\]")
LOOKUP_ERRORS = (AttributeError, KeyError, IndexError, TypeError, ValueError)

def _parse_path(path):
    """'a.b[0]["x"]' -> [('attr','a'), ('attr','b'), ('item',0), ('item','x')]
    Bare names are attributes; brackets are subscripts."""
    path = path.strip()
    steps, pos = [], 0
    for m in _PATH_TOKEN.finditer(path):
        if m.start() != pos:
            raise ValueError(f"can't parse path {path!r}")
        name, key = m.groups()
        if name is not None:
            steps.append(("attr", name))
        else:
            try:
                key = ast.literal_eval(key)
            except (ValueError, SyntaxError):
                pass
            steps.append(("item", key))
        pos = m.end()
    if not steps or pos != len(path):
        raise ValueError(f"can't parse path {path!r}")
    return steps

def _resolve(root, path):
    obj = root
    for kind, key in _parse_path(path):
        obj = getattr(obj, key) if kind == "attr" else obj[key]
    return obj

def _set(root, path, value):
    steps = _parse_path(path)
    parent = root
    for kind, key in steps[:-1]:
        parent = getattr(parent, key) if kind == "attr" else parent[key]
    kind, key = steps[-1]
    if kind == "attr":
        setattr(parent, key, value)
    else:
        parent[key] = value

def _coerce(value):
    if not isinstance(value, str):
        return value
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value

def _describe(obj, ui):
    ui.post(
        f"[cyan]{type(obj).__module__}.{type(obj).__qualname__}[/cyan]"
        + (" (callable)" if callable(obj) else "")
    )

    if inspect.isroutine(obj):
        try:
            ui.post(str(inspect.signature(obj)))
        except (TypeError, ValueError):
            pass

    state = getattr(obj, "__dict__", None)

    if state:
        for name, value in state.items():
            ui.post(f"  {name}: {value!r}")
    else:
        names = [n for n in dir(obj) if not n.startswith("_")]
        ui.post(names)

    return obj
# --- policy: the command itself, now just dispatch ---------------------------

def repl_command(repl, *args, **kwargs):
    console = repl.ui_console

    # /repl  or  /repl show  -> list attributes
    if (not args and not kwargs) or (len(args) == 1 and args[0] == "show"):
        names = [n for n in dir(repl) if not n.startswith("_")]
        repl.ui_messages.post(names)
        return names

    # /repl key=value ... -> set
    if not args:
        for k, v in kwargs.items():
            v = _coerce(v)
            try:
                _set(repl, k, v)
            except LOOKUP_ERRORS as e:
                repl.ui_messages.post(f"[red]Could not set {k}: {e}[/red]")
                continue
            msg = f"Setting {k} to {v!r}"
            logger.info(msg)
            repl.ui_messages.post(f"[yellow]{msg}[/yellow]")
        return

    if args[0] == "help":
        if len(args) > 1:
            try:
                attr = _resolve(repl, args[1])
            except LOOKUP_ERRORS:
                repl.ui_messages.post(f"[red]No such attribute: {args[1]}[/red]")
                return
            try:
                repl.ui_messages.post(str(inspect.signature(attr)))
            except (TypeError, ValueError):
                pass
            doc = inspect.getdoc(attr)
            if doc:
                repl.ui_messages.post(doc)
        repl.ui_messages.post("/repl show [name] inspects | name() calls | name=value sets")
        return

    # /repl show <path> -> inspect anything, never call
    inspect_only = args[0] == "show"
    if inspect_only:
        args = args[1:]

    # /repl name() -> explicit call
    target = args[0]
    force_call = target.endswith("()")
    if force_call:
        target = target[:-2]

    try:
        attr = _resolve(repl, target)
    except LOOKUP_ERRORS:
        repl.ui_messages.post("[red]Command not found.[/red]")
        return None

    if inspect_only:
        return _describe(attr, repl.ui_messages)

    if force_call or (callable(attr) and (len(args) > 1 or kwargs or inspect.isroutine(attr))):
        try:
            return attr(*args[1:], **kwargs)
        except Exception as e:
            repl.ui_messages.post(f"[red]{type(e).__name__}: {e}[/red]")
            return None

    return _describe(attr, repl.ui_messages)
def profile_command(repl, *args, **kwargs):
    console = repl.ui_console
    repl.ui_messages.post(Panel(repl.profile_manager.get_profile_string(), title="User Profile"))
    repl.ui_messages.post("[yellow]Profile saved.[/yellow]")

def quit_command(repl, *args, **kwargs):
    console = repl.ui_console
    repl.ui_messages.post("[yellow]Goodbye![/yellow]")
    repl.shutdown()
    repl.status="stop"
    return "quit"

def stub(repl, *args, **kwargs):
            return "stub"

def help(repl, *args, **kwargs):
    console = repl.ui_console
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
    repl.ui_messages.post(help_text + cmd_help)

def system_prompt_command(repl, *args, **kwargs):
    console = repl.ui_console
    if len(args) < 1:
        repl.ui_messages.post(f"[blue]Current system prompt[/blue]: {repl.system_prompt}")
        return
    with repl._state_lock:
        repl.base_system_prompt = args[0].strip()
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    repl.ui_messages.post("[yellow]System prompt updated.[/yellow]")

def backend_command(repl, *args, **kwargs):
    try:
        old_backend = [repl.backend, repl.api.port, repl.api.model, repl.client]
    except AttributeError:
        old_backend = [repl.backend, None, None, None]

    console = repl.ui_console

    if len(args) < 1:
        repl.ui_messages.post(f"availabe backends: {', '.join(BACKEND_MAP.keys())} (default: {repl.backend})")
        return
    with repl._state_lock:
        if args[0] not in BACKEND_MAP.keys():
            repl.ui_messages.post(f"[red]Backend {args} not found in {BACKEND_MAP.keys()}[/red]")
            return
        repl.backend = args[0]
        try:
            port =  kwargs.get("port")
            model = kwargs.get("model")
            base_url = kwargs.get("base_url")
            api = _switch_repl_backend(repl, repl.backend, port=port, model=model, base_url=base_url)
            repl.api = api
        except (ConnectError, HTTPError, ValueError) as e:
            logger.exception(e)
            pd = " ".join(args[1:])
            repl.ui_messages.post(f"[red]Failed to switch backend: {pd}{e}[/red]")
            repl.backend = old_backend[0]
            return
        logger.debug("reloading profiles")
        repl.prompt_gen.reload_profiles()
        repl.base_system_prompt = repl.prompt_gen.generate_prompt(repl.current_role)
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    # save conf
    save_config(repl)
    repl.ui_messages.post(f"[yellow]Backend switched to: {repl.backend}[/yellow]")
    repl._draw_statusbar(force=True)

def tools_command(repl, *args, **kwargs):
    console = repl.ui_console
    if "reload" in args:
        repl.skills_manager.discover_skills()
        repl.tool_registry = repl.create_tool_registry(repl)
        repl.ui_messages.post("[yellow]Tools reloaded.[/yellow]")
        return
    elif "off" in args:
        repl.notools = True
        repl.ui_messages.post("[yellow]Tools disabled.[/yellow]")
        return
    elif "on" in args:
        repl.notools = False
        repl.ui_messages.post("[yellow]Tools enabled.[/yellow]")
        return
    elif args and len(args) > 1:
        if "allow" == args[0]:
            repl.tool_registry.disable_tool("*")
            for arg in args[1:]:
                repl.tool_registry.enable_tool(arg)
            return
        elif "deny" == args[0]:
            repl.tool_registry.enable_tool("*")
            for arg in args[1:]:
                repl.tool_registry.disable_tool(arg)
            return
        elif "disable" == args[0]:
            for arg in args[1:]:
                repl.tool_registry.disable_tool(arg)
            return
        elif "enable" == args[0]:
            # Enable specific tools, respecting ban list
            for arg in args[1:]:
                if repl.tool_registry.enable_tool_if_not_banned(arg):
                    repl.ui_messages.post(f"[green]Enabled tool: {arg}[/green]")
                else:
                    repl.ui_messages.post(f"[red]Cannot enable '{arg}': tool is banned or not found[/red]")
            return
        elif "enable_all" == args[0]:
            # Enable all non-banned tools
            enabled_count = 0
            for tool_name in repl.tool_registry._tools.keys():
                if not repl.tool_registry.is_banned(tool_name):
                    repl.tool_registry.enable_tool(tool_name)
                    enabled_count += 1
            repl.ui_messages.post(f"[green]Enabled {enabled_count} non-banned tools[/green]")
            return
        elif "ban" == args[0]:
            # Ban tools permanently
            for arg in args[1:]:
                repl.tool_registry.ban_tool(arg)
                repl.ui_messages.post(f"[red]Banned tool: {arg}[/red]")
            return
        elif "unban" == args[0]:
            # Unban tools
            for arg in args[1:]:
                repl.tool_registry.unban_tool(arg)
                repl.ui_messages.post(f"[green]Unbanned tool: {arg}[/green]")
            return
        elif "banned" == args[0]:
            # List banned tools
            banned = repl.tool_registry.get_banned_tools()
            repl.ui_messages.post("[red]Banned tools:[/red]")
            if banned:
                repl.ui_messages.post(f' - {", ".join(banned)}')
            else:
                repl.ui_messages.post("  (none)")
            return

    # repl.ui_messages.post("[yellow]Available skills:[/yellow]")
    # repl.ui_messages.post(repl.skills_manager.get_catalog_summary())
    # for skill_id, meta in repl.skills_manager.catalog.items() or {}:
    #     repl.ui_messages.post(f"  - {meta.name}: {meta.description}")
    repl.ui_messages.post("[yellow]Available tools:[/yellow]")
    repl.ui_messages.post(f' - {", ".join(repl.tool_registry.list_tools())}')
    repl.ui_messages.post("[yellow]Disabled tools:[/yellow]")
    repl.ui_messages.post(f' - {", ".join(repl.tool_registry._disabled_tools)}')
    repl.ui_messages.post("[yellow]Banned tools:[/yellow]")
    banned = repl.tool_registry.get_banned_tools()
    if banned:
        repl.ui_messages.post(f' - {", ".join(banned)}')
    else:
        repl.ui_messages.post("  (none)")


def task_command(repl, *args, **kwargs):
    console = repl.ui_console
    tasks: dict = repl.tasks

    # Todo: Switch task color by state?
    if "rm" in args and "idx" in kwargs:
        repl.tasks.pop(int(kwargs["idx"]))
        repl.ui_messages.post("[yellow]Task removed.[/yellow]")
    elif "rm" in args and "all" in args:
        repl.tasks = {}
        repl.ui_messages.post("[yellow]All tasks removed.[/yellow]")
    elif len(args) == 0 and "idx" in kwargs:
        repl.ui_messages.post(f"[green]Task {kwargs['idx']}[/green]: {tasks.get(int(kwargs['idx']))}")
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
        repl.ui_messages.post(f"[green]Task {task_text[:40]}[...] added.[/green]")
        if len(kwargs) > 0:
            if "delay" in kwargs:
                delay_length = kwargs["delay"]
                if delay_length.isnumeric():
                    delay_length = int(delay_length)
                    #repl.loop_task.set_end(datetime.now() + timedelta(seconds=delay_length))
                message = Message("user", task_text)
                message.send_time = time.time() + delay_length
                message.params["task_id"] = task_id
                repl.input_queue.put(message)
    else:
        repl.ui_messages.post("[yellow]Available tasks:[/yellow]")
        for idx, task in repl.tasks.items():
            repl.ui_messages.post(f"  - {idx}: {task['task'][:60]}")


def config_command(repl, *args, **kwargs):
    get_config_representation(repl)
    console = repl.ui_console
    if "save" in args:
        save_config(repl)
        repl.ui_messages.post("[yellow]Config saved.[/yellow]")
        return
    elif "load" in args:
        load_config(repl)
        repl.ui_messages.post("[yellow]Config loaded.[/yellow]")
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
        repl.ui_messages.post("[yellow]Config:[/yellow]")
        yaml_str = yaml.dump(repl.config).replace("[", r"\[").replace("]", r"\]")
        repl.ui_messages.post(Markdown(f"```yaml\n{yaml_str}\n```"))

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
            "enabled_tools",
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
    if getattr(repl, "api"):
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

    # repl.ui_messages.post(Markdown(f"```yaml\n{yaml.dump(repl_representation)}\n```"))
    with open(Path.cwd() / "llm_repl.yaml", "w") as f:
        yaml.dump(repl_representation, f)

def load_config(repl, *args, **kwargs) -> Optional[LLMBackend] :
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
            if k in ["aliases", "api"]:
                continue
            repl.__dict__[k] = v if v is not None else repl.__dict__.get(k, None)
    if repl.__dict__.get("enabled_tools"):
        repl.tool_registry.disable_tool("*")
        for tool in repl.enabled_tools:
            repl.tool_registry.enable_tool(tool)

    try:
        port = conf.get("port", repl.port)
        backend=conf.get("backend", repl.backend)
        model = conf.get("model", None)
        base_url = conf.get("base_url", None)
        repl.api = _switch_repl_backend(repl, backend=backend, port=port, model=model, base_url=base_url)

    except Exception as e:
        repl.ui_messages.post(f"[red]Failed to switch backend: {e}[/red]")
        return repl.api #In whatever state
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
    console = repl.ui_console
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
    repl.ui_messages.post(table)
    if "save" in args:
        repl.save_conversation_history()

def role_command(repl, *args, **kwargs):
    console = repl.ui_console
    with repl._state_lock:
        repl.current_role = args[0]
        repl.prompt_gen.reload_profiles()
        repl.base_system_prompt = repl.prompt_gen.generate_prompt(repl.current_role)
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    repl.ui_messages.post(f"[yellow]Role switched to: {repl.current_role}[/yellow]")

def model_command(repl, *args, **kwargs):
    console = repl.ui_console
    if len(args) < 1:
        model_str = "\n\t".join(repl.api.available_models)
        repl.ui_messages.post(f'availabe models: \n\t{model_str} (default: {repl.model})')
        return
    repl.api.model = repl.api.find_model(args[0].strip())
    repl.model = repl.api.model or args[0].strip()

    repl.ui_messages.post(f"[yellow]Model switched to: {repl.model}[/yellow]")

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
        return (f"[red]Failed to read file: {e}[/red]")

def load_command(repl, *args, **kwargs):
    fname = args[0].strip()
    contents = _read_file(fname)
    if not contents:
        return f"Failed to read file {fname}"

    fence = _make_fence(contents)
    message = f"Contents of {fname}:\n{fence}\n{contents}\n{fence}\n"


    # Fire it to the background queue instead of blocking
    if not repl.agent_active:
        repl._start_background_send(message)
    else:
        repl.pending_user_inputs.put(message)
    return (message)
def read_command(repl, *args, **kwargs):
    console = repl.ui_console
    if len(args) < 1:
        cwd = Path.cwd()
        repl.ui_messages.post("current directory: " + str(cwd))
        files = '\n\t'.join([str(p) for p in cwd.glob('*')])
        repl.ui_messages.post(f"available files: \n{files}")
        return
    fname = args[0].strip()
    contents = _read_file(fname)
    if contents:
        #repl.ui_messages.post(f"Contents of {fname}:\n{fence}\n{contents}\n{fence}")
        repl.ui_messages.post(contents) # raw output

def shell_command(repl, *args, **kwargs):
    console = repl.ui_console
    # Join the args back into a single string so the user can use shell operators
    command_str = " ".join(args)
    repl.ui_messages.post(f"[dim]Executing: {command_str}[/dim]")

    # Use the robust _run_bash function we refined
    result = run_bash(command_str, cwd=str(WORKSPACE_DIR))

    repl.ui_messages.post(result)