import shlex
from typing import Dict, Callable, Any
import logging
import os

logger = logging.getLogger(__name__)
if os.getenv("DEBUG") == "true":
    logger.setLevel(logging.DEBUG)
logger.setLevel(logging.ERROR)

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
        logger.debug(entry)
        return entry["handler"](self.repl, *args, **kwargs)

    def load(self, commands_dict: Dict[str, Callable], command_definitions: Dict[str, Dict[str, Any]]):
        for name, handler in commands_dict.items():
            help_text = command_definitions[name].get("help", "")
            aliases = command_definitions[name].get("aliases", [])
            self.register(name, handler, help_text, aliases)

    def get_help(self):
        # Generate help from unique command entries.
        ...

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
