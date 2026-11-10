# agent_tools.py
import os
import platform
import sys
import subprocess
#import logging
from typing import List, Union
import json
from pathlib import Path

try:
    import tools
except ImportError:
    # Fallback if tools is not in the python path
    # In a real deployment, we'd ensure it's in the same directory or package
    if Path(__file__).parent.parent not in sys.path:
        sys.path.append(str(Path(__file__).parent.parent))
from tools import AGENT_DIR, TOOLS_DIR, WORKSPACE_DIR
from tools.internet_tools import INTERNET_TOOL_MAP, INTERNET_TOOL_DEFINITION_MAP
from tools.agent_deb_tools import install_deb_package
from tools.bash_tools import run_bash
from tools.cloud_image_gen import CLOUD_IMAGE_GEN_TOOL_DEFINITION, generate_cloud_image

try:
    from tools.tmux_tools import TMUX_TOOL_MAP, TMUX_TOOL_DEFINITION_MAP
except Exception:
    TMUX_TOOL_MAP = {}
    TMUX_TOOL_DEFINITION_MAP = {}

# Import the new context tools
try:
    from tools.context_tools import CONTEXT_TOOL_MAP, CONTEXT_TOOL_DEFINITION_MAP
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

BG_TIMEOUT = TOOL_TIMEOUT

from custom_logger import setup_logging


logger = setup_logging("AgentTools")

def _is_memory_file(path: str) -> bool:
    """Check if the given path is the protected memory file."""
    memory_path = WORKSPACE_DIR / "memory.md"
    try:
        return Path(path).resolve() == memory_path
    except Exception as e:
        logger.error(f"Error checking memory file: {e}")
        return False

class CacheFile:
    def __init__(self, path: str, lines: List[str]):
        self.path = path
        self.lines = lines
        # NOTE: could use st_mtime_ns instead
        self.stat: os.stat_result = os.stat(path)

class Files:
    open_files = {}

    def get_open_files(self):
        return self.open_files

    def add_file(self, path: Union[str, Path], lines: List[str]):
        self.open_files[path] = CacheFile(str(path), lines)

    def read_file(self, path: Union[str, Path]):
        stat = os.stat(path)
        if path in self.open_files:
            cached=self.open_files[path]

            if cached.stat.st_mtime == stat.st_mtime:
                return cached.lines
        self.add_file(path, _read_file_all(path))
        return self.open_files[path].lines

files = Files()

# --- Tool Implementations ---

def tool_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

DEFAULT_READ_CHARS = 12_000
MAX_READ_CHARS = 24_000


def _read_file_all(path: Union[str, Path],) -> List[str]:
    path = _relative_paths_helper(str(path))

    p = Path(path).expanduser().resolve()

    if not p.exists():
        raise FileNotFoundError(f"Error: file does not exist: {p}")
    if not p.is_file():
        raise FileNotFoundError(f"Error: not a regular file: {p}")

    lines = []
    # Read text, not a fixed number of bytes.
    with p.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    return lines

def read_file(
    path: str,
    start_line: int = 1,
    max_lines: int = 0,
    max_chars: int = DEFAULT_READ_CHARS,):
    """ Read lines from a file. with paging and utf-8 encoding. """
    try:
        lines = files.read_file(path)
        total_lines = len(lines)
        if start_line < 1 or start_line > total_lines + 1:
            return (
                f"Error: start_line must be between 1 and "
                f"{total_lines + 1}; file has {total_lines} lines."
            )

        max_chars = max(1, min(max_chars, MAX_READ_CHARS))
        start_idx = start_line - 1
        end_idx = total_lines if max_lines <= 0 else min(
            total_lines, start_idx + max_lines)


        selected = []
        chars = 0
        next_line = None


        for idx in range(start_idx, end_idx):
            line = lines[idx]
            if selected and chars + len(line) > max_chars:
                break
            selected.append(line)
            chars += len(line)

        if next_line is None and end_idx < total_lines:
            next_line = end_idx + 1

        actual_end = start_idx + len(selected)

        header = (
            f"File: {path}\n"
            f"Total lines: {total_lines}\n"
            f"Showing lines {start_line} - {actual_end}; "
            f"returned {len(selected)} line(s).\n"
        )

        if next_line is not None:
            header += (
                f"TRUNCATED: more content remains. "
                f"Continue with start_line={next_line}.\n"
            )
        else:
            header += "End of requested content reached.\n"

        return header + "\n--- CONTENT ---\n" + "".join(selected)
    except FileNotFoundError as e:
        return f"Error: {e}"

    except Exception as e:
        return f"Error reading {path}: {e}"

def replace_lines_in_file(path: Union[str, Path], lines: List[str], start_line: int, orig_lines: List[str]) -> str:
    path = _relative_paths_helper(str(path))
    try:
        file_lines = files.read_file(path)
        check_lines = file_lines[start_line-1:start_line-1+len(orig_lines)]
        logger.debug (f"Check lines:{check_lines}")
        if len(check_lines) != len(orig_lines):
            return "Error: original lines do not match"
        for i, line in enumerate(check_lines):
            if line.rstrip() != orig_lines[i].rstrip():
                return f"Error: lines do not match"
        new_lines = file_lines[:start_line - 1] + [f"{l.rstrip()}\n" for l in lines] + file_lines[start_line-1+len(orig_lines):]
        logger.debug(f"New lines: {new_lines}")
        with open(f"{path}.tmp", 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        tmp_path = Path(f"{path}.tmp")
        if not tmp_path.exists():
            raise IOError("Temporary file was not created")
        if tmp_path.read_text(encoding="utf-8") != "".join(new_lines):
            raise IOError("Temporary file verification failed")
        os.replace(tmp_path, path)
        files.open_files.pop(path, None)
        return f"Successfully replaced lines in {path}"
    except Exception as e:
        return f"Error replacing lines in file: {e}"


def read_file_lines(path: str, start_line: int = 1, end_line: int = None) -> str:
    """Read specific lines of a file (1-indexed)."""
    logger.info(f"Reading lines {start_line} to {end_line} of file: {path}")
    path = _relative_paths_helper(path)
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
    path = _relative_paths_helper(path)
    logger.info(f"Searching for '{query}' in file: {path}")
    def _search_file(path: str, query: str) -> list[str]:
        matches = []
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if query in line:
                    matches.append(f'line {i}: found "{line}"')
        return matches

    try:
        matches = []
        if not Path(path).is_file():
            if Path(path).is_dir():
                #let's help them out...
                files = {file: _search_file(file, query) for file in _glob_files(path, recurse=True)}
                result =  "\n".join([f"{file}:\n{matches}" for file, matches in files.items()]) or "No matches found."
                if len(result) > MAX_OUTPUT_LENGTH:
                    result = f"Too many matches. Truncated output:\n\n{result[:MAX_OUTPUT_LENGTH]}..."
                return f"Searched files in {path}:\n{result}"
                # return f"Error: not a regular file: {path} were you trying to search a directory?"
            return f"Error: not a regular file: {path} were you trying to search a directory?"

        matches = _search_file(path, query)

        if not matches:
            return "No matches found."

        result = "".join(matches)
        if len(result) > MAX_OUTPUT_LENGTH:
            return f"Too many matches. Truncated output:\n\n{result[:MAX_OUTPUT_LENGTH]}..."
        return result
    except Exception as e:
        return f"Error searching file: {str(e)}"

def _relative_paths_helper(path: str) -> str:
    if not ("/" in path or "\\" in path):
        # if path.startswith(".\\") or path.startswith(r"./"):
        #     path = path.lstrip("./\\")
        path = str(Path(path).resolve())
    return path

def _glob_files(path, filterstr="*", recurse=False):
    if recurse:
        files = [str(p) for p in Path(path).rglob(filterstr)]
    else:
        files = [str(p) for p in Path(path).glob(filterstr)]
    return files

def list_files(path: str = ".", filterstr: str = "*", recurse: bool = False) -> str:
    """List files and directories in a given path."""
    ignorelist = [
        ".git", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".venv"
    ]

    path = _relative_paths_helper(path)
    logger.info(f"Listing files in: {path}")
    try:
        files = [f for f in _glob_files(path, filterstr, recurse) if Path(f).name not in ignorelist]
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

    if path in files.open_files:
        del files.open_files[path]

    logger.info("Writing file: %s", path)
    return write_or_append_file(
        path, content, mode="w", message=f"Successfully wrote {len(content)} chars to {path}")

def append_file(path: str, content: str) -> str:
    """Append content to a file."""
    logger.info("Appending to file: %s", path)
    return write_or_append_file(
        path, content, mode="a", message=f"Successfully appended {len(content)} chars to {path}")

def write_or_append_file(path: str, content: str, mode: str = "a", message: str = None) -> str:
    path = _relative_paths_helper(path)
    try:
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        return message or f"Successfully wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error appending to file: {e}"

global _repl_state
_repl_state = {}

def python_repl(code: str) -> str:
    """Execute Python code in a persistent REPL session."""
    # Use RestrictedPython or subprocess with timeout
    # Maintain session state between calls
    global _repl_state
    if not _repl_state:
        _repl_state = {}
        if os.path.exists(WORKSPACE_DIR / "repl_state.json"):
            with open(WORKSPACE_DIR / "repl_state.json", "r") as f:
                _repl_state = json.load(f)
    session_globals = _repl_state.get("globals", {})
    session_locals = _repl_state.get("locals", {})
    try:
        # timeout = 10 # TODO: Make this configurable
        from background_util import run_in_background
        import time

        bg = run_in_background(lambda: exec(code, session_globals, session_locals))
        try:
            result = bg.wait(timeout=BG_TIMEOUT)
        except Exception as e:
            logger.error(f"Error in python_repl: {e}")
            results = bg.stop()
            return f"Error: {e}; results: {results}"
        _repl_state["globals"] = session_globals
        _repl_state["locals"] = session_locals
        return str(result) if result else "OK"
    except Exception as e:
        return f"Error: {e}"

# Tool Mapping
TOOL_MAP = {
    "run_bash": run_bash,
    "read_file": read_file,
    "read_file_lines": read_file_lines,
    "replace_lines": replace_lines_in_file,
    "search_file": search_file,
    "list_files": list_files,
    "write_file": write_file,
    "append_file": append_file,
    "install_deb_package": install_deb_package,
    "now": tool_now,
    **INTERNET_TOOL_MAP,
    **TMUX_TOOL_MAP,
    **CONTEXT_TOOL_MAP,
    "generate_cloud_image": generate_cloud_image,
    "python_repl": python_repl
}

bash_description = "Execute a bash command. Use /tmp or /workspace for writes."
if platform.system() == "Windows":
    bash_description = "Execute a shell command. Use allowed directiories for writes."

# Tool definitions for the LLM
tools = [
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": "Replace lines in a file. Safe for large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "string"}},
                    "start_line": {"type": "integer"},
                    "orig_lines": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path", "lines", "start_line", "orig_lines"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "python_repl",
            "description": "execute python code in a persistent REPL session",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": bash_description,
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"},
                               "executable": {"type": "string", "description": "default: bash"},
                               "cwd": {"type": "string", "description": f"default: {WORKSPACE_DIR}"},},
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
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "description": "Start line (inclusive), default 1"},
                    "max_lines": {"type": "integer", "description": "Maximum number of lines to read, default 0 (unlimited)"},
                    "max_chars": {"type": "integer", "description": "Maximum number of characters to read"}
                    },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_lines",
            "description": "Read specific lines of a file (1-indexed), with added line numbers. Useful for large files"
                " or to figure out what lines to replace when editing code. ",
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
            "description": "Search for a LITERAL substring (case-sensitive). No regex, no boolean operators, no 'OR'. For pattern/boolean search, use run_bash with rg (ripgrep).",
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
                "properties": {"path": {"type": "string", "description": "Path to list, defaults to current directory"},
                               "filterstr": {"type": "string", "description": "Filter files by name"},
                               "recurse": {"type": "boolean", "description": "Recurse into subdirectories"},
                               },
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
            "name": "append_file",
            "description": "Append content to a file by path.",
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
tools.append(CLOUD_IMAGE_GEN_TOOL_DEFINITION)

TOOL_DEFINITIONS = tools

if __name__=="__main__":
    pass
# Moved test to tests; have not tested since.