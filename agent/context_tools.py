import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ContextTools")

# --- Configuration ---
CONTEXT_FILES = {
    "memory": "memory.md",
    "plan": "plan.md",
    "todo": "todo.md"
}

def _update_context_file(file_key: str, content: str, mode: str = "append") -> str:
    """Internal helper to update context files."""
    filename = CONTEXT_FILES.get(file_key)
    if not filename:
        return f"Error: Invalid file key '{file_key}'"
    
    # Use absolute path if possible, or relative to workspace
    # For this environment, we assume files are in /workspace/
    path = os.path.join("/workspace", filename)
    
    try:
        if mode == "append":
            timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f"\n\n### {timestamp}\n{content}\n")
            return f"Successfully appended to {filename}"
        
        elif mode == "prepend":
            existing_content = ""
            if os.path.exists(path):
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

def update_memory(content: str, mode: str = "append") -> str:
    """Update the agent's memory.md file. Use 'append' to add new information, 'prepend' for high priority, or 'replace' to rewrite."""
    return _update_context_file("memory", content, mode)

def update_plan(content: str, mode: str = "append") -> str:
    """Update the agent's plan.md file. Use 'append' to add new steps, 'prepend' for high priority, or 'replace' to rewrite."""
    return _update_context_file("plan", content, mode)

def update_todo(content: str, mode: str = "append") -> str:
    """Update the agent's todo.md file. Use 'append' to add new tasks, 'prepend' for high priority, or 'replace' to rewrite."""
    return _update_context_file("todo", content, mode)

# --- Tool Mapping ---
CONTEXT_TOOL_MAP = {
    "update_memory": update_memory,
    "update_plan": update_plan,
    "update_todo": update_todo
}

# --- Tool Definitions ---
def _create_definition(name, description):
    return {
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

CONTEXT_TOOL_DEFINITION_MAP = {
    "update_memory": _create_definition("update_memory", "Update the agent's memory.md file. Use this for long-term knowledge and context."),
    "update_plan": _create_definition("update_plan", "Update the agent's plan.md file. Use this for the current high-level execution strategy."),
    "update_todo": _create_definition("update_todo", "Update the agent's todo.md file. Use this for tracking specific tasks."),
}
