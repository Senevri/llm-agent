"""Tmux-backed LLM-callable tools for persistent shell contexts.

No import side effects: importing this module never starts a tmux server.
"""

import logging
import os
import re
import subprocess
import time

logger = logging.getLogger("TmuxAgentTools")

# --- Configuration (module-level, from env) ---
TMUX_BIN = os.getenv("AGENT_TMUX_BIN", "tmux")
TMUX_SOCKET = os.getenv("AGENT_TMUX_SOCKET", "agent")
TMUX_PREFIX = os.getenv("AGENT_TMUX_PREFIX", "agent-")
MAX_CAPTURE = int(os.getenv("AGENT_TMUX_MAX_CAPTURE", "20000"))


def _tmux(*args, timeout=10):
    """Run a tmux command on the agent socket. Argv only, never shell=True."""
    return subprocess.run(
        [TMUX_BIN, "-L", TMUX_SOCKET, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _validate_name(name):
    """Validate a tmux session name. Raises ValueError on failure."""
    if not isinstance(name, str) or not name:
        raise ValueError("Session name must be a non-empty string.")
    if not name.startswith(TMUX_PREFIX):
        raise ValueError(
            f"Session name {name!r} must start with prefix {TMUX_PREFIX!r}."
        )
    if len(name) > 64:
        raise ValueError(
            f"Session name {name!r} exceeds 64 characters ({len(name)})."
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError(
            f"Session name {name!r} contains invalid characters; "
            "allowed: A-Z a-z 0-9 _ . -"
        )
    return name


def _cap(text):
    """Apply the capture character cap."""
    if text is None:
        text = ""
    if len(text) > MAX_CAPTURE:
        return f"Output truncated to {MAX_CAPTURE} characters:\n\n{text[:MAX_CAPTURE]}..."
    return text


def _err(prefix, exc):
    return f"Error: {prefix}: {exc}"


# --- Tool implementations ---

def tmux_create_session(name, command=None, cwd=None):
    """Create a detached tmux session owned by the agent.

    Args:
        name: Session name (must begin with AGENT_TMUX_PREFIX).
        command: Optional command to send once the session is created.
        cwd: Optional working directory; must exist.

    Returns:
        A human-readable status string.
    """
    logger.info(f"tmux create_session: name={name}, cwd={cwd}")
    try:
        name = _validate_name(name)
        if cwd is not None and not os.path.isdir(cwd):
            return f"Error: cwd does not exist: {cwd}"
        args = ["new-session", "-d", "-s", name]
        if cwd is not None:
            args += ["-c", cwd]
        res = _tmux(*args)
        if res.returncode != 0:
            msg = (res.stderr or res.stdout or "").strip()
            return f"Error creating session {name}: {msg or 'unknown error'}"
        if command is not None:
            # Small settle delay; harmless if unnecessary.
            time.sleep(0.05)
            r2 = _tmux("send-keys", "-t", name, str(command), "Enter")
            if r2.returncode == 0:
                time.sleep(0.1)
            if r2.returncode != 0:
                msg = (r2.stderr or r2.stdout or "").strip()
                return (
                    f"Created session {name}, but failed to send initial command: "
                    f"{msg or 'unknown error'}"
                )
        return f"Created tmux session: {name}"
    except Exception as e:
        logger.error(f"tmux create_session error: {e}")
        return f"Error creating session {name}: {e}"


def tmux_send(session, input, literal=False, wait=0.5):
    """Send input to a tmux session, optionally wait, and return the capture.

    Completion-detection race (the one race in this feature): ``wait`` is
    best-effort. ``tmux_send`` sleeps up to ``wait`` seconds and returns the
    current pane capture; the command may still be running. For deterministic
    completion, use a marker and poll::

        tmux_send(s, "make build; echo __DONE_$?__", wait=5)
        # if "__DONE_0__" not in the returned capture:
        tmux_capture(s, lines=50)  # poll again

    Args:
        session: Agent-owned session name.
        input: Text/keys to send.
        literal: If True, send the text literally (no key-name translation).
        wait: Seconds to wait before capturing (default 0.5).

    Returns:
        Recent pane output (capped at AGENT_TMUX_MAX_CAPTURE chars).
    """
    logger.info(f"tmux send: session={session}, wait={wait}, literal={literal}")
    try:
        session = _validate_name(session)
        if literal:
            r = _tmux("send-keys", "-t", session, "-l", str(input))
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or "").strip()
                return f"Error sending input to {session}: {msg or 'unknown error'}"
            # Literal text alone does not execute; press Enter to run it.
            _tmux("send-keys", "-t", session, "Enter")
        else:
            r = _tmux("send-keys", "-t", session, str(input), "Enter")
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or "").strip()
                return f"Error sending input to {session}: {msg or 'unknown error'}"

        try:
            wait_time = float(wait)
        except (TypeError, ValueError):
            wait_time = 0.0
        if wait_time > 0:
            time.sleep(wait_time)

        return tmux_capture(session, lines=200)
    except Exception as e:
        logger.error(f"tmux send error: {e}")
        return f"Error sending input to {session}: {e}"


def tmux_capture(session, lines=100):
    """Capture recent output from a tmux pane.

    Args:
        session: Agent-owned session name.
        lines: Number of trailing lines to capture (default 100).

    Returns:
        Pane output (capped at AGENT_TMUX_MAX_CAPTURE chars).
    """
    logger.info(f"tmux capture: session={session}, lines={lines}")
    try:
        session = _validate_name(session)
        args = ["capture-pane", "-t", session, "-p", "-J"]
        try:
            n = int(lines)
        except (TypeError, ValueError):
            n = 100
        if n > 0:
            args += ["-S", f"-{n}"]
        res = _tmux(*args)
        if res.returncode != 0:
            msg = (res.stderr or res.stdout or "").strip()
            # Common case: session does not exist.
            return f"Error capturing session {session}: {msg or 'unknown error'}"
        output = res.stdout or ""
        # Trim a trailing newline for cleanliness, keep meaningful trailing spaces.
        return _cap(output.rstrip("\n"))
    except Exception as e:
        logger.error(f"tmux capture error: {e}")
        return f"Error capturing session {session}: {e}"


def tmux_list():
    """List agent-owned tmux sessions on the agent socket."""
    logger.info("tmux list")
    try:
        res = _tmux("list-sessions", "-F", "#{session_name}")
        if res.returncode != 0:
            msg = (res.stderr or res.stdout or "").strip().lower()
            if "no server" in msg or "no sessions" in msg or "failed to connect" in msg:
                return "No agent sessions."
            # Could be another error; report it.
            raw = (res.stderr or res.stdout or "").strip()
            if not raw:
                return "No agent sessions."
            return f"Error listing sessions: {raw}"
        sessions = [s for s in (res.stdout or "").splitlines() if s.strip()]
        owned = [s for s in sessions if s.startswith(TMUX_PREFIX)]
        if not owned:
            return "No agent sessions."
        return "\n".join(owned)
    except Exception as e:
        logger.error(f"tmux list error: {e}")
        return f"Error listing sessions: {e}"


def tmux_kill(session):
    """Kill one agent-owned tmux session.

    Args:
        session: Agent-owned session name.

    Returns:
        A human-readable status string.
    """
    logger.info(f"tmux kill: session={session}")
    try:
        session = _validate_name(session)
        res = _tmux("kill-session", "-t", session)
        if res.returncode != 0:
            msg = (res.stderr or res.stdout or "").strip()
            return f"Error killing session {session}: {msg or 'unknown error'}"
        return f"Killed tmux session: {session}"
    except Exception as e:
        logger.error(f"tmux kill error: {e}")
        return f"Error killing session {session}: {e}"


# --- Export maps (mirroring INTERNET_TOOL_* pattern) ---

tmux_create_session_tool_definition = {
    "type": "function",
    "function": {
        "name": "tmux_create_session",
        "description": (
            "Create a detached tmux session on the agent socket. "
            "Use for long builds, background processes, or interactive programs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Session name (must start with the agent prefix)."},
                "command": {"type": "string", "description": "Optional command to run once created."},
                "cwd": {"type": "string", "description": "Optional working directory; must exist."},
            },
            "required": ["name"],
        },
    },
}

tmux_send_tool_definition = {
    "type": "function",
    "function": {
        "name": "tmux_send",
        "description": (
            "Send input to a tmux session, optionally wait, then return the capture. "
            "wait is best-effort: the command may still be running afterwards. "
            "For deterministic completion, send a marker and poll, e.g. "
            "tmux_send(s, \"make build; echo __DONE_$?__\", wait=5) then, if "
            "__DONE_0__ is not in the capture, tmux_capture(s, lines=50)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session": {"type": "string", "description": "Agent-owned session name."},
                "input": {"type": "string", "description": "Text/keys to send."},
                "literal": {"type": "boolean", "description": "Send text literally when true. Default false."},
                "wait": {"type": "number", "description": "Seconds to wait before capturing. Default 0.5."},
            },
            "required": ["session", "input"],
        },
    },
}

tmux_capture_tool_definition = {
    "type": "function",
    "function": {
        "name": "tmux_capture",
        "description": "Read recent output from a tmux pane.",
        "parameters": {
            "type": "object",
            "properties": {
                "session": {"type": "string", "description": "Agent-owned session name."},
                "lines": {"type": "integer", "description": "Trailing lines to capture (default 100)."},
            },
            "required": ["session"],
        },
    },
}

tmux_list_tool_definition = {
    "type": "function",
    "function": {
        "name": "tmux_list",
        "description": "List agent-owned tmux sessions.",
        "parameters": {"type": "object", "properties": {}},
    },
}

tmux_kill_tool_definition = {
    "type": "function",
    "function": {
        "name": "tmux_kill",
        "description": "Kill one agent-owned tmux session.",
        "parameters": {
            "type": "object",
            "properties": {
                "session": {"type": "string", "description": "Agent-owned session name."},
            },
            "required": ["session"],
        },
    },
}

TMUX_TOOL_MAP = {
    "tmux_create_session": tmux_create_session,
    "tmux_send": tmux_send,
    "tmux_capture": tmux_capture,
    "tmux_list": tmux_list,
    "tmux_kill": tmux_kill,
}

TMUX_TOOL_DEFINITION_MAP = {
    "tmux_create_session": tmux_create_session_tool_definition,
    "tmux_send": tmux_send_tool_definition,
    "tmux_capture": tmux_capture_tool_definition,
    "tmux_list": tmux_list_tool_definition,
    "tmux_kill": tmux_kill_tool_definition,
}
