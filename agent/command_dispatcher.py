from typing import Dict, Callable, Any


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