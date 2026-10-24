# ollama_agent_tools.py
import os
import subprocess
import logging
import json
from internet_tools import INTERNET_TOOL_MAP, INTERNET_TOOL_DEFINITION_MAP
from bash_tools import run_bash

from datetime import datetime, timezone

# --- Configuration ---
# Note: These are defaults. In a more robust system, these could be passed from the main agent.
TOOL_TIMEOUT = int(os.getenv("AGENT_TOOL_TIMEOUT", "60"))
MAX_OUTPUT_LENGTH = int(os.getenv("AGENT_MAX_OUTPUT_LENGTH", "20000"))

logger = logging.getLogger("OllamaAgentTools")

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
    """Write content to a file."""
    logger.info(f"Writing file: {path}")
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"



# Tool Mapping
TOOL_MAP = {
    "run_bash": run_bash,
    "read_file": read_file,
    "read_file_lines": read_file_lines,
    "search_file": search_file,
    "list_files": list_files,
    "write_file": write_file,
    **INTERNET_TOOL_MAP
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
                "required": ["path"]
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
    }
]

# Add internet tools to the tool definitions
tools.extend(INTERNET_TOOL_DEFINITION_MAP.values())
