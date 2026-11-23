"""Regression tests for slashcommands and command_dispatcher."""

import pytest
import shlex
from unittest.mock import MagicMock, patch
from pathlib import Path

from command_dispatcher import CommandDispatcher, parse_command
from slashcommands import load_commands, Script


# ---------------------------------------------------------------------------
# parse_command regression tests
# ---------------------------------------------------------------------------

class TestParseCommand:
    """Test parse_command from command_dispatcher."""

    def test_simple_command(self):
        cmd, pos, kw, err = parse_command("/help")
        assert cmd == "help"
        assert pos == []
        assert kw == {}
        assert err is None

    def test_command_with_positional(self):
        cmd, pos, kw, err = parse_command("/model gpt-4")
        assert cmd == "model"
        assert pos == ["gpt-4"]
        assert kw == {}

    def test_command_with_kwargs(self):
        cmd, pos, kw, err = parse_command("/backend ollama port=11434 model=llama3")
        assert cmd == "backend"
        assert pos == ["ollama"]
        assert kw == {"port": "11434", "model": "llama3"}

    def test_command_with_mixed_args(self):
        cmd, pos, kw, err = parse_command("/todo add fix bug delay=30")
        assert cmd == "todo"
        assert pos == ["add", "fix", "bug"]
        assert kw == {"delay": "30"}

    def test_empty_input(self):
        cmd, pos, kw, err = parse_command("")
        assert cmd is None
        assert pos == []
        assert kw == {}

    def test_whitespace_only(self):
        cmd, pos, kw, err = parse_command("   ")
        assert cmd is None

    def test_quoted_string(self):
        cmd, pos, kw, err = parse_command('/shell "echo hello world"')
        assert cmd == "shell"
        assert pos == ["echo hello world"]

    def test_no_slash_prefix(self):
        cmd, pos, kw, err = parse_command("help")
        assert cmd == "help"

    def test_nested_quotes(self):
        cmd, pos, kw, err = parse_command('/shell echo "hello" "world"')
        assert cmd == "shell"
        assert pos == ["echo", "hello", "world"]

    def test_equals_in_value(self):
        cmd, pos, kw, err = parse_command('/config set base_url=http://localhost:8080')
        assert cmd == "config"
        assert kw == {"base_url": "http://localhost:8080"}


# ---------------------------------------------------------------------------
# CommandDispatcher regression tests
# ---------------------------------------------------------------------------

class TestCommandDispatcher:
    """Test CommandDispatcher from command_dispatcher."""

    def setup_method(self):
        self.repl = MagicMock()
        self.dispatcher = CommandDispatcher(self.repl)

    def test_register_and_dispatch(self):
        handler = MagicMock(return_value="ok")
        self.dispatcher.register("test", handler, "test help")
        result = self.dispatcher.dispatch("test", ["arg1"], {"key": "val"})
        handler.assert_called_once_with(self.repl, "arg1", key="val")
        assert result == "ok"

    def test_dispatch_unknown_command(self):
        result = self.dispatcher.dispatch("nonexistent", [], {})
        assert result is None

    def test_register_with_aliases(self):
        handler = MagicMock(return_value="alias_ok")
        self.dispatcher.register("main", handler, aliases=["m", "main-alias"])
        assert "main" in self.dispatcher.commands
        assert "m" in self.dispatcher.commands
        assert "main-alias" in self.dispatcher.commands
        # All aliases point to same handler
        assert self.dispatcher.commands["main"] is self.dispatcher.commands["m"]

    def test_dispatch_via_alias(self):
        handler = MagicMock(return_value="alias_works")
        self.dispatcher.register("main", handler, aliases=["m"])
        result = self.dispatcher.dispatch("m", [], {})
        assert result == "alias_works"

    def test_dispatch_type_error(self):
        handler = MagicMock(side_effect=TypeError("wrong signature"))
        self.dispatcher.register("bad", handler)
        result = self.dispatcher.dispatch("bad", ["too", "many"], {})
        assert "Error" in result

    def test_load_commands_dict(self):
        cmds = {"cmd1": MagicMock(return_value="r1"), "cmd2": MagicMock(return_value="r2")}
        defs = {
            "cmd1": {"help": "help1", "aliases": ["c1"]},
            "cmd2": {"help": "help2"},
        }
        self.dispatcher.load(cmds, defs)
        assert "cmd1" in self.dispatcher.commands
        assert "c1" in self.dispatcher.commands
        assert "cmd2" in self.dispatcher.commands

    def test_load_overwrites_existing(self):
        """load() replaces existing commands (current behavior)."""
        existing = MagicMock(return_value="existing")
        self.dispatcher.register("cmd", existing)
        new_handler = MagicMock(return_value="new")
        cmds = {"cmd": new_handler}
        defs = {"cmd": {"help": "new help"}}
        self.dispatcher.load(cmds, defs)
        # load() overwrites existing handler
        assert self.dispatcher.commands["cmd"]["handler"] is new_handler


# ---------------------------------------------------------------------------
# load_commands regression tests
# ---------------------------------------------------------------------------

class TestLoadCommands:
    """Test load_commands from slashcommands."""

    def test_returns_two_dicts(self):
        commands, definitions = load_commands()
        assert isinstance(commands, dict)
        assert isinstance(definitions, dict)

    def test_all_definitions_have_help(self):
        _, definitions = load_commands()
        for name, defn in definitions.items():
            assert "help" in defn, f"{name} missing 'help' key"

    def test_quit_has_aliases(self):
        _, definitions = load_commands()
        quit_aliases = definitions["quit"].get("aliases", [])
        assert "quit" in quit_aliases
        assert "q" in quit_aliases
        assert "exit" in quit_aliases
        assert "bye" in quit_aliases

    def test_command_handlers_exist(self):
        commands, _ = load_commands()
        # Verify all command names have callable handlers
        for name in commands:
            assert callable(commands[name]), f"{name} handler is not callable"

    def test_no_orphan_definitions(self):
        """Every definition should have a corresponding handler."""
        commands, definitions = load_commands()
        for name in definitions:
            assert name in commands, f"Definition '{name}' has no handler"

    def test_no_orphan_handlers(self):
        """Every handler should have a corresponding definition."""
        commands, definitions = load_commands()
        for name in commands:
            assert name in definitions, f"Handler '{name}' has no definition"

    def test_expected_commands_present(self):
        commands, _ = load_commands()
        expected = [
            "quit", "clear", "sys", "model", "history", "profile",
            "role", "backend", "help", "loop", "todo", "read",
            "load", "tools", "config", "shell", "repl", "status", "alias",
        ]
        for name in expected:
            assert name in commands, f"Missing expected command: {name}"


# ---------------------------------------------------------------------------
# Script (alias executor) regression tests
# ---------------------------------------------------------------------------

class TestScript:
    """Test Script class for alias execution."""

    def test_python_eval_expression(self):
        repl = MagicMock()
        s = Script(repl, "python", "2 + 3")
        result = s(repl)
        assert result == 5

    def test_python_exec_statements(self):
        repl = MagicMock()
        s = Script(repl, "python", "x = 10\ny = 20\nz = x + y")
        result = s(repl)
        assert result is None  # exec returns None

    def test_python_syntax_error(self):
        repl = MagicMock()
        s = Script(repl, "python", "def broken(")
        # SyntaxError in both eval and exec modes propagates
        with pytest.raises(SyntaxError):
            s(repl)

    def test_str_representation_long(self):
        repl = MagicMock()
        s = Script(repl, "python", "x = 1; y = 2; z = 3; a = 4; b = 5")
        s_repr = str(s)
        assert "```" in s_repr  # fenced representation

    def test_str_representation_short(self):
        repl = MagicMock()
        s = Script(repl, "python", "x=1")
        s_repr = str(s)
        assert "#" in s_repr  # short representation

    def test_repr_matches_str(self):
        repl = MagicMock()
        s = Script(repl, "python", "x=1")
        assert repr(s) == str(s)


# ---------------------------------------------------------------------------
# Command function regression tests (with mock repl)
# ---------------------------------------------------------------------------

class TestCommandFunctions:
    """Test individual command functions with a mock repl."""

    def _make_repl(self):
        repl = MagicMock()
        repl.system_prompt = "test system prompt"
        repl.base_system_prompt = "test base"
        repl.messages = [{"role": "system", "content": "test"}]
        repl._state_lock = MagicMock()
        repl.ui_messages = MagicMock()
        repl.ui_messages.post = MagicMock()
        repl.ui_console = MagicMock()
        repl.profile_manager = MagicMock()
        repl.profile_manager.get_profile_string = MagicMock(return_value="profile data")
        repl.api = MagicMock()
        repl.api.usage = MagicMock()
        repl.api.usage.summary = MagicMock(return_value="0% context")
        repl.tasks = {}
        repl.aliases = {}
        repl.cmd_dispatcher = MagicMock()
        repl.cmd_dispatcher.commands = {}
        repl.agent_active = False
        repl.pending_user_inputs = MagicMock()
        repl._start_background_send = MagicMock()
        repl.shutdown = MagicMock()
        repl.status = "running"
        repl.current_bg_task = None
        return repl

    def test_quit_command(self):
        from slashcommands import quit_command
        repl = self._make_repl()
        result = quit_command(repl)
        assert result == "quit"
        repl.shutdown.assert_called_once()
        assert repl.status == "stop"

    def test_clear_command(self):
        from slashcommands import clear_command
        repl = self._make_repl()
        repl.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        clear_command(repl)
        assert len(repl.messages) == 1
        assert repl.messages[0]["role"] == "system"

    def test_system_prompt_no_args(self):
        from slashcommands import system_prompt_command
        repl = self._make_repl()
        repl._build_system_prompt = MagicMock(return_value="built prompt")
        system_prompt_command(repl)
        repl.ui_messages.post.assert_called()

    def test_system_prompt_set_args(self):
        from slashcommands import system_prompt_command
        repl = self._make_repl()
        repl._build_system_prompt = MagicMock(return_value="new built prompt")
        system_prompt_command(repl, "new system prompt")
        assert repl.base_system_prompt == "new system prompt"

    def test_profile_command(self):
        from slashcommands import profile_command
        repl = self._make_repl()
        profile_command(repl)
        repl.profile_manager.get_profile_string.assert_called_once()

    def test_alias_list_no_args(self):
        from slashcommands import alias_command
        repl = self._make_repl()
        repl.aliases = {"myalias": "some command"}
        alias_command(repl)
        repl.ui_messages.post.assert_called()

    def test_alias_set_command(self):
        from slashcommands import alias_command
        repl = self._make_repl()
        repl.aliases = {}
        repl.cmd_dispatcher.commands = {}
        alias_command(repl, "set", "myalias", "somecommand")
        assert "myalias" in repl.aliases

    def test_alias_rm(self):
        from slashcommands import alias_command
        repl = self._make_repl()
        repl.aliases = {"myalias": "some command"}
        # Note: alias_command has a bug - "rm" handling requires >2 args
        # This test documents the actual behavior
        alias_command(repl, "rm", "myalias", "dummy")  # 3 args to trigger rm block
        assert "myalias" not in repl.aliases

    def test_todo_add(self):
        from slashcommands import task_command
        repl = self._make_repl()
        task_command(repl, "add", "fix bug")
        assert len(repl.tasks) > 0
        task_id = max(repl.tasks)
        # Actual behavior: task text includes "add" prefix
        assert repl.tasks[task_id]["task"] == "add fix bug"
    def test_todo_list_empty(self):
        from slashcommands import task_command
        repl = self._make_repl()
        repl.tasks = {}
        task_command(repl)
        repl.ui_messages.post.assert_called()

    def test_todo_rm_idx(self):
        from slashcommands import task_command
        repl = self._make_repl()
        repl.tasks = {0: {"task": "task0"}, 1: {"task": "task1"}}
        task_command(repl, "rm", idx=0)
        assert 0 not in repl.tasks

    def test_todo_rm_all(self):
        from slashcommands import task_command
        repl = self._make_repl()
        repl.tasks = {0: {"task": "task0"}, 1: {"task": "task1"}}
        task_command(repl, "rm", "all")
        assert repl.tasks == {}

    def test_read_no_args(self):
        from slashcommands import read_command
        repl = self._make_repl()
        read_command(repl)
        repl.ui_messages.post.assert_called()

    def test_status_command(self):
        from slashcommands import status_command
        repl = self._make_repl()
        status_command(repl)
        repl.ui_messages.post.assert_called()

    def test_help_command(self):
        from slashcommands import help
        repl = self._make_repl()
        help(repl)
        repl.ui_messages.post.assert_called()


# ---------------------------------------------------------------------------
# Integration: parse + dispatch round-trip
# ---------------------------------------------------------------------------

class TestIntegration:
    """Test parse_command + CommandDispatcher round-trip."""

    def test_roundtrip_simple(self):
        text = "/help"
        cmd, pos, kw, err = parse_command(text)
        assert err is None
        assert cmd == "help"

    def test_roundtrip_with_kwargs(self):
        text = "/backend ollama port=8080 model=llama3"
        cmd, pos, kw, err = parse_command(text)
        assert err is None
        assert cmd == "backend"
        assert pos == ["ollama"]
        assert kw == {"port": "8080", "model": "llama3"}

    def test_roundtrip_todo_add(self):
        text = "/todo add implement feature delay=60"
        cmd, pos, kw, err = parse_command(text)
        assert err is None
        assert cmd == "todo"
        assert pos == ["add", "implement", "feature"]
        assert kw == {"delay": "60"}

    def test_roundtrip_shell_quoted(self):
        text = '/shell "ls -la | grep test"'
        cmd, pos, kw, err = parse_command(text)
        assert err is None
        assert cmd == "shell"
        assert pos == ["ls -la | grep test"]

    def test_roundtrip_config_set(self):
        text = "/config set n_ctx=4096"
        cmd, pos, kw, err = parse_command(text)
        assert err is None
        assert cmd == "config"
        assert kw == {"n_ctx": "4096"}
