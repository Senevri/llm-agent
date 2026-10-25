# ollama_agent_tools.py
import os
import subprocess
import logging
import json
from internet_tools import INTERNET_TOOL_MAP, INTERNET_TOOL_DEFINITION_MAP
from agent_deb_tools import install_deb_package
from bash_tools import run_bash
from pathlib import Path
try:
    from tmux_tools import TMUX_TOOL_MAP, TMUX_TOOL_DEFINITION_MAP
except Exception:
    TMUX_TOOL_MAP = {}
    TMUX_TOOL_DEFINITION_MAP = {}

# Import the new context tools
try:
    from agent.context_tools import CONTEXT_TOOL_MAP, CONTEXT_TOOL_DEFINITION_MAP
except ImportError:
    # Fallback if context_tools is not in the python path
    # In a real deployment, we'd ensure it's in the same directory or package
    CONTEXT_TOOL_MAP = {}
    CONTEXT_TOOL_DEFINITION_MAP = {}

from datetime import datetime, timezone

# --- Configuration ---
# Note: These are defaults. In a more robust system, these could be passed from the main agent.
TOOL_TIMEOUT = int(os.getenv("AGENT_TOOL_TIMEOUT", "60"))
MAX_OUTPUT_LENGTH = int(os.getenv("AGENT_MAX_OUTPUT_LENGTH", "20000"))

logger = logging.getLogger("OllamaAgentTools")

def _is_memory_file(path: str) -> bool:
    """Check if the given path is the protected memory file."""
    memory_path = Path("/workspace/memory.md").resolve()
    try:
        return Path(path).resolve() == memory_path
    except Exception as e:
        logger.error(f"Error checking memory file: {e}")
        return False

# --- Tool Implementations ---

def tool_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def read_file(path: str) -> str:
    """Read the contents of a file."""
    logger.info(f"Reading file: {path}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            if len(content) > MAX_OUTPUT_LENGTH:
                return f"File too large. Please use read_file_lines or search_file. (Size: {len(content)} chars)"
            return content
    except Exception as e:
        return f"Error reading file: {str(e)}"

def read_file_lines(path: str, start_line: int = 1, end_line: int = None) -> str:
    """Read specific lines of a file (1-indexed)."""
    logger.info(f"Reading lines {start_line} to {end_line} of file: {path}")
    try:
        lines_read = []
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if i < start_line:
                    continue
                if end_line and i > end_line:
                    break
                lines_read.append(f"{i}: {line}")
        return "".join(lines_read) if lines_read else "No lines found in the specified range."
    except Exception as e:
        return f"Error reading lines: {str(e)}"

def search_file(path: str, query: str) -> str:
    """Search for a string within a file and return matching lines with line numbers."""
    logger.info(f"Searching for '{query}' in file: {path}")
    try:
        matches = []
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if query in line:
                    matches.append(f"{i}: {line}")

        if not matches:
            return "No matches found."

        result = "".join(matches)
        if len(result) > MAX_OUTPUT_LENGTH:
            return f"Too many matches. Truncated output:\n\n{result[:MAX_OUTPUT_LENGTH]}..."
        return result
    except Exception as e:
        return f"Error searching file: {str(e)}"

def list_files(path: str = ".") -> str:
    """List files and directories in a given path."""
    logger.info(f"Listing files in: {path}")
    try:
        files = os.listdir(path)
        return "\n".join(files) if files else "Directory is empty."
    except Exception as e:
        return f"Error listing files: {str(e)}"

def write_file(path: str, content: str) -> str:
    """Write a file, except protected memory files."""
    if _is_memory_file(path):
        return (
            "Permission denied: memory.md is protected from write_file. "
            "Use update_memory to append an entry."
        )

    logger.info("Writing file: %s", path)
    write_or_append_file(
        path, content, mode="w", message="Successfully wrote {len(content)} chars to {path}")

def append_file(path: str, content: str) -> str:
    """Append content to a file."""
    logger.info("Appending to file: %s", path)
    write_or_append_file(
        path, content, mode="a", message="Successfully appended {len(content)} chars to {path}")

def write_or_append_file(path: str, content: str, mode: str = "a", message: str = None) -> str:
    try:
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        return messsage or f"Successfully wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error appending to file: {e}"

# Tool Mapping
TOOL_MAP = {
    "run_bash": run_bash,
    "read_file": read_file,
    "read_file_lines": read_file_lines,
    "search_file": search_file,
    "list_files": list_files,
    "write_file": write_file,
    "install_deb_package": install_deb_package,
    "now": tool_now,
    **INTERNET_TOOL_MAP,
    **TMUX_TOOL_MAP,
    **CONTEXT_TOOL_MAP
}

# Tool definitions for the LLM
tools = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Execute a bash command. Use /tmp or /workspace for writes.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file by path. Fails if file is too large.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "path": {"type": "string"}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_lines",
            "description": "Read specific lines of a file (1-indexed). Useful for large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "description": "Start line (inclusive), default 1"},
                    "end_line": {"type": "integer", "description": "End line (inclusive)"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_file",
            "description": "Search for a LITERAL substring (case-sensitive). No regex, no boolean operators, no 'OR'. For pattern/boolean search, use run_bash with rg.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "query": {"type": "string"}
                },
                "required": ["path", "query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in a given path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path to list, defaults to current directory"}},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file by path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "now",
            "description": "Get the current date and time in ISO 8601 format.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "install_deb_package",
            "description": (
            "Install a Debian/Ubuntu package into ~/.local WITHOUT root, by downloading the "
            ".deb and extracting it (dpkg -x). Binaries go to ~/.local/bin (on PATH). "
            "Does NOT run maintainer scripts and does NOT put shared libraries on the "
            "linker path. Use this when a package is available in apt sources but the "
            "system apt is locked (non-root, read-only /). For Python packages use "
            "`pip install --user` instead."
            ),
            "parameters": {
            "type": "object",
            "properties": {
                "package": {"type": "string", "description": "Debian package name, e.g. 'jq' or 'libimage-exiftool-perl'."},
                "with_deps": {"type": "boolean", "description": "Also fetch direct runtime dependencies (not already installed). Default true."}
            },
            "required": ["package"]
            }
        }
    }
]

# Add other tool definitions
tools.extend(INTERNET_TOOL_DEFINITION_MAP.values())
tools.extend(TMUX_TOOL_DEFINITION_MAP.values())
tools.extend(CONTEXT_TOOL_DEFINITION_MAP.values())
