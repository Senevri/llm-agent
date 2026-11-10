# context_tools.py
import os
import logging
import shutil
import tempfile
from datetime import datetime, timezone

logger = logging.getLogger("ContextTools")

# --- Configuration ---
CONTEXT_FILES = {
    "memory": "memory.md",
    "plan": "plan.md",
    "todo": "todo.md"
}

# --- Memory compression ---

from pathlib import Path
from tools import WORKSPACE_DIR


MEMORY_PATH = WORKSPACE_DIR / "memory.md"
MEMORY_COMPRESSION_THRESHOLD = int(
    os.getenv("AGENT_MEMORY_COMPRESSION_THRESHOLD", "12000")
)
MEMORY_MIN_REDUCTION = float(
    os.getenv("AGENT_MEMORY_MIN_REDUCTION", "0.15")
)

def set_memory_path(path: Path):
    """Set the path to the memory file. Useful per-project basis <WIP> """
    global MEMORY_PATH
    MEMORY_PATH = path

def _update_context_file(file_key: str, content: str, mode: str = "append") -> str:
    """Internal helper to update context files."""
    filename = CONTEXT_FILES.get(file_key)
    if not filename:
        return f"Error: Invalid file key '{file_key}'"

    # Use absolute path if possible, or relative to workspace
    # For this environment, we assume files are in /workspace/
    path = WORKSPACE_DIR / filename
    logger.info(f"Updating {path} with mode {mode}")

    try:
        if mode == "append":
            timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f"\n\n### {timestamp}\n{content}\n")
            return f"Successfully appended to {filename}"

        elif mode == "prepend":
            existing_content = ""
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    existing_content = f.read()

            timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f"### {timestamp}\n{content}\n\n{existing_content}")
            return f"Successfully prepended to {filename}"

        elif mode == "replace":
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully replaced content of {filename}"

        else:
            return f"Error: Invalid mode '{mode}'. Use 'append', 'prepend', or 'replace'."

    except Exception as e:
        logger.error(f"Error updating {filename}: {str(e)}")
        return f"Error updating {filename}: {str(e)}"


def compress_memory(compressed_content: str) -> str:
    """
    Replace memory with a model-proposed concise version, but only when
    memory exceeds the configured threshold and the proposal is smaller.

    A timestamped backup is preserved before replacement.
    """
    if not compressed_content or not compressed_content.strip():
        return "Error: compressed memory cannot be empty."

    path = MEMORY_PATH

    try:
        if not path.is_file():
            return f"Error: memory file not found: {path}"

        original = open(path, "r", encoding="utf-8").read()
        original_size = len(original)
        proposed_size = len(compressed_content)

        if original_size <= MEMORY_COMPRESSION_THRESHOLD:
            return (
                f"No compression needed: memory is {original_size} characters; "
                f"threshold is {MEMORY_COMPRESSION_THRESHOLD}."
            )

        required_size = int(
            original_size * (1.0 - MEMORY_MIN_REDUCTION)
        )
        if proposed_size > required_size:
            return (
                f"Compression rejected: original is {original_size} characters, "
                f"proposal is {proposed_size}. "
                f"At least {MEMORY_MIN_REDUCTION:.0%} reduction is required."
            )

        # Keep the backup next to memory.md; don't create a new directory.
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = f"{path}.{timestamp}.bak"
        shutil.copy2(path, backup_path)

        # Write a temporary file in the same directory for atomic replacement.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=os.path.dirname(path),
                prefix=".memory_compress_",
                suffix=".tmp",
                delete=False,
            ) as temp:
                temp_path = temp.name
                temp.write(compressed_content.rstrip() + "\n")
                temp.flush()
                os.fsync(temp.fileno())

            # Preserve original permissions.
            os.chmod(temp_path, os.stat(path).st_mode)
            os.replace(temp_path, path)
            temp_path = None

        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

        logger.info(
            "Compressed memory: %d -> %d chars; backup: %s",
            original_size,
            proposed_size,
            backup_path,
        )
        return (
            f"Memory compressed successfully: {original_size} -> "
            f"{proposed_size} characters. "
            f"Backup preserved at {backup_path}."
        )

    except Exception as e:
        logger.exception("Memory compression failed")
        return f"Error compressing memory: {e}"

def _tail_memory(n: int) -> str:
    path = Path(MEMORY_PATH).resolve()
    try:
        if not path.is_file():
            return f"Error: memory file not found: {path}"

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception as e:
        logger.error(f"Error tailing memory: {e}")
        return f"Error tailing memory: {e}"

def update_memory(content: str, mode: str = "append") -> str:
    """Update the agent's memory.md file. Use 'append' to add new information, 'prepend' for high priority, or 'replace' to rewrite."""
    return _update_context_file("memory", content, "append")

def update_plan(content: str, mode: str = "append") -> str:
    """Update the agent's plan.md file. Use 'append' to add new steps, 'prepend' for high priority, or 'replace' to rewrite."""
    return _update_context_file("plan", content, mode)

def update_todo(content: str, mode: str = "append") -> str:
    """Update the agent's todo.md file. Use 'append' to add new tasks, 'prepend' for high priority, or 'replace' to rewrite."""
    return _update_context_file("todo", content, mode)

def tail_memory(n: int) -> str:
    return _tail_memory(n)

# --- Tool Mapping ---
CONTEXT_TOOL_MAP = {
    "update_memory": update_memory,
    "update_plan": update_plan,
    "update_todo": update_todo,
    "compress_memory": compress_memory,
    "get_recent_memory": tail_memory
}

# --- Tool Definitions ---
def _create_definition(name, description, properties=None, required=None):
    if properties is None:
        properties = {}

    template = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The content to write/append"},
                    "mode": {
                        "type": "string",
                        "description": "How to update the file: 'append' (default), 'prepend', or 'replace'",
                        "enum": ["append", "prepend", "replace"]
                    }
                },
                "required": ["content"]
            }
        }
    }

    if properties:
        template["function"]["parameters"]["properties"].update(properties)

    if required:
        template["function"]["parameters"]["required"] = required

    return template

CONTEXT_TOOL_DEFINITION_MAP = {
    "update_memory": _create_definition("update_memory", "Update the agent's memory.md file. Use this for long-term knowledge and context."),
    "update_plan": _create_definition("update_plan", "Update the agent's plan.md file. Use this for the current high-level execution strategy."),
    "update_todo": _create_definition("update_todo", "Update the agent's todo.md file. Use this for tracking specific tasks."),
    "get_recent_memory": _create_definition("get_recent_memory", "Get the last N lines of the agent's memory.md file.",
                                      properties={"n": {"type": "integer", "minimum": 1}}, required=["n"]),
    "compress_memory": {
        "type": "function",
        "function": {
            "name": "compress_memory",
            "description": (
                "Replace memory.md with a concise version of its existing contents. "
                "First back up the old version by copying it to a new file. "
                "Then read the entire memory file and prepare a faithful summary. "
                "Preserve durable facts, preferences, project decisions, constraints, "
                "and unresolved tasks. Do not invent information. "
                "The tool only commits changes when memory exceeds its configured "
                "size threshold and the proposal achieves the required size reduction. "
                "A backup is created before replacement. "
                "Do not use this to update ordinary new information; use update_memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "compressed_content": {
                        "type": "string",
                        "description": (
                            "The complete proposed replacement for memory.md, "
                            "preserving all important existing information."
                        )
                    }
                },
                "required": ["compressed_content"]
            }
        }
    },
}
