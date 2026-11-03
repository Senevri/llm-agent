
import os
import json
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

try:
    from custom_logger import setup_logging
    logger = setup_logging("ToolRegistry")
except ImportError:
    import logging
    logger = logging.getLogger("ToolRegistry")

class Tool:
    """A tool definition combining metadata and implementation."""
    def __init__(self, name: str, description: str, func: Callable, parameters: Dict[str, Any]):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert tool metadata to OpenAI function calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


class PathAccessError(Exception):
    pass


def resolve_allowed_path(path: str, roots: list[Path]) -> Path:
    candidate = Path(path).expanduser().resolve()

    for root in roots:
        root = root.resolve()
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue

    raise PathAccessError(f"Path outside permitted workspace: {path}\nAllowed root paths: {roots}")

class ToolRegistry:
    """Registry for managing and dispatching agent tools."""
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._disabled_tools = set(t for t in os.getenv("DISABLED_TOOLS", "").split(",") if t)
        self._allowed_paths = [Path(p) for p in os.getenv("ALLOWED_PATHS", "").split(",") if p]
        self._allowed_paths.append(Path.cwd())

    def get_allowed_paths(self) -> str:
        return "\n".join(str(p) for p in self._allowed_paths)

    def allow_path(self, path: Path):
        self._allowed_paths.append(path)

    def register(self, name: str, description: str, func: Callable, parameters: Dict[str, Any]):
        """Register a new tool."""
        if name in self._tools:
            logger.warning(f"Tool '{name}' is already registered. Overwriting.")

        self._tools[name] = Tool(name, description, func, parameters)
        logger.info(f"Tool '{name}' registered successfully.")

    def disable_tool(self, name: str):
        """Disable a tool by name."""
        self._disabled_tools.add(name)

    def enable_tool(self, name: str):
        """Enable a tool by name."""
        self._disabled_tools.discard(name)


    def get_tool(self, name: str) -> Optional[Tool]:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def execute(self, tool_name: str, **kwargs) -> str:
        """Execute a tool by name with provided arguments."""
        tool = self.get_tool(tool_name)
        if not tool:
            return f"Error: Tool '{tool_name}' not found in registry."

        try:
            # Simple validation: check if all required parameters are present
            required = self._get_required_params(tool.parameters)
            missing = [p for p in required if p not in kwargs]
            if missing:
                return f"Error: Tool '{tool_name}' is missing required arguments: {missing}"

            # validate policy:
            kwargs = self._validate_policy(tool_name, tool, kwargs)

            result = tool.func(**kwargs)

            if result is None:
                logger.error("Tool '%s' returned None", tool_name)
                return f"Error: tool '{tool_name}' returned None instead of a result."

            if not isinstance(result, str):
                result = str(result)

            return result
        except Exception as e:
            logger.exception(f"Error executing tool '{tool_name}': {e}")
            return f"Error executing tool '{tool_name}': {str(e)}"

    def _validate_policy(self, tool_name, tool, kwargs) -> dict:
        if tool_name in self._disabled_tools:
            return f"Error: Tool '{tool_name}' is disabled."
        # Check allowed paths
        for k, v in tool.parameters.get("properties", {}).items():
            if (k in ["path", "cwd"]
                or "path" in k):
                path = kwargs.get(k)
                if path:
                    path = resolve_allowed_path(path, self._allowed_paths)
                    kwargs[k] = str(path)
            # check if v is path
            try:
                if v.get("type") == "string":
                    path = Path(kwargs.get(k))
                    # Still don't know if it is a path.
            except Exception as e:
                # Probably not a path
                pass
        return kwargs

    def _get_required_params(self, parameters: Dict[str, Any]) -> List[str]:
        """Extract required parameters from JSON schema."""
        try:
            return parameters.get("required", [])
        except Exception:
            return []

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(k for k in self._tools.keys() if k not in self._disabled_tools)

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """Get OpenAI schemas for all registered tools."""
        return [tool.to_openai_schema() for tool in self._tools.values() if tool.name not in self._disabled_tools]

    def get_map(self) -> Dict[str, Callable]:
        """Return a mapping of name to function for legacy support."""
        return {name: tool.func for name, tool in self._tools.items() if name not in self._disabled_tools}

registry = ToolRegistry()
logger.info(f"Tool registry initialized. Allowed paths: {registry._allowed_paths}")
