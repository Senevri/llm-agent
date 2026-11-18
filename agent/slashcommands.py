from loop_task import loop
from pathlib import Path
import os
import re
import sys
import yaml
import inspect
import textwrap
import logging


from httpx2 import ConnectError, HTTPError

from tools import WORKSPACE_DIR
from llm_utils import _role
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

def alias_command(repl, *args, **kwargs):
    console = repl.console
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

    console.print(f"[yellow]Alias {args[1]} set to {args[2]}[/yellow]") # type: ignore

def clear_command(repl, *args, **kwargs):
    console = repl.console
    with repl._state_lock:
        repl.messages = [
            {"role": "system", "content": repl.system_prompt}
        ]
    console.print("[yellow]Conversation history cleared.[/yellow]")

def status_command(repl, *args, **kwargs):
    # TODO: other status here?
    repl.no_reply = False
    repl._draw_statusbar()
    console = repl.console
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
    console = repl.console
    def _parse_attr(attr):
        if "." in attr:
            class_chain = attr.split(".")
            attr = getattr(repl, class_chain[0])
            for c in class_chain[1:]:
                attr = getattr(attr, c)
        # if "[" in attr:
        #     dict_chain = attr.split("[").rstrip("]")
        #     attr = getattr(repl, dict_chain[0])

        else:
            attr = getattr(repl, attr)
        return attr
    if len(args) == 0:
        if len(kwargs)>0:
            for k, v in kwargs.items():
                attr = _parse_attr(k)
                if attr:
                    msg = f"Setting {k} to {v}"
                    v = v =="True" if v in ["True", "False"] else v
                    try:
                        v = eval(v)
                    except:
                        pass
                    if v.isnumeric():
                        v = int(v)
                    if isinstance(attr, dict):
                        attr[k] = v
                    elif not callable(attr):
                        attr = v
                    else:
                        setattr(attr, k, v=="True" if v in ["True", "False"] else v)

                    logger.info(msg)
                    console.print(f"[yellow]{msg}[/yellow]")
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
    console = repl.console
    console.print(Panel(repl.profile_manager.get_profile_string(), title="User Profile"))
    console.print("[yellow]Profile saved.[/yellow]")

def quit_command(repl, *args, **kwargs):
    console = repl.console
    console.print("[yellow]Goodbye![/yellow]")
    repl.shutdown()
    return "quit"

def stub(repl, *args, **kwargs):
            return "stub"

def help(repl, *args, **kwargs):
    console = repl.console
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
    console = repl.console
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

    console = repl.console

    if len(args) < 1:
        console.print(f"availabe backends: {', '.join(BACKEND_MAP.keys())} (default: {repl.backend})")
        return
    with repl._state_lock:
        if args[0] not in BACKEND_MAP.keys():
            console.print(f"[red]Backend {args} not found in {BACKEND_MAP.keys()}[/red]")
            return
        repl.backend = args[0]
        try:
            port =  kwargs.get("port")
            api = LLMBackend(backend=repl.backend, defer_init=True, port=port)
            api.port = port or api.port
            api.model = kwargs.get("model", api.model)
            api.base_url = kwargs.get("base_url", api.base_url)
            api._get_endpoint()
            api.model = api.endpoint.model
            api.base_url = api.endpoint.base_url.rstrip("/")
            api.port = api.endpoint.port
            repl.client, repl.model = api.get_client()
            repl.api = api
        except (ConnectError, HTTPError) as e:
            pd = " ".join(args[1:])
            console.print(f"[red]Failed to switch backend: {pd}{e}[/red]")
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
    console = repl.console
    if "reload" in args:
        repl.skills_manager.discover_skills()
        repl.tool_registry = repl.create_tool_registry(repl)
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
            for arg in args[1:]:
                repl.tool_registry.enable_tool(arg)
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
    console = repl.console
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
    console = repl.console
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
        yaml_str = yaml.dump(repl.config).replace("[", r"\[").replace("]", r"\]")
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
            if k in ["aliases", "api"]:
                continue
            repl.__dict__[k] = v if v is not None else repl.__dict__.get(k, None)
    if repl.__dict__.get("enabled_tools"):
        repl.tool_registry.disable_tool("*")
        for tool in repl.enabled_tools:
            repl.tool_registry.enable_tool(tool)

    try:
        port = conf.get("port", repl.port)
        repl.api = LLMBackend(backend=conf.get("backend", repl.backend), defer_init=True, port=port)
        repl.api.port = port
        repl.api.model = conf.get("model", repl.api.model)
        repl.api.base_url = conf.get("base_url", repl.api.base_url)
        repl.api._get_endpoint()
        repl.client, repl.model = repl.api.get_client()
    except Exception as e:
        repl.console.print(f"[red]Failed to switch backend: {e}[/red]")
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
    console = repl.console
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
    console = repl.console
    with repl._state_lock:
        repl.current_role = args[0]
        repl.prompt_gen.reload_profiles()
        repl.base_system_prompt = repl.prompt_gen.generate_prompt(repl.current_role)
        repl.system_prompt = repl._build_system_prompt()
        repl.messages = [{"role": "system", "content": repl.system_prompt}] + repl.messages[1:]
    console.print(f"[yellow]Role switched to: {repl.current_role}[/yellow]")

def model_command(repl, *args, **kwargs):
    console = repl.console
    if len(args) < 1:
        model_str = "\n\t".join(repl.api.available_models)
        console.print(f'availabe models: \n\t{model_str} (default: {repl.model})')
        return
    repl.api.model = repl.api.find_model(args[0].strip())
    repl.model = repl.api.model or args[0].strip()

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
    console = repl.console
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
    console = repl.console
    # Join the args back into a single string so the user can use shell operators
    command_str = " ".join(args)
    console.print(f"[dim]Executing: {command_str}[/dim]")

    # Use the robust _run_bash function we refined
    result = run_bash(command_str, cwd=str(WORKSPACE_DIR))

    console.print(result)