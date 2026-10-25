import logging
import os
import json
from typing import Dict, Any, List, Optional, Callable

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

class ToolRegistry:
    """Registry for managing and dispatching agent tools."""
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, name: str, description: str, func: Callable, parameters: Dict[str, Any]):
        """Register a new tool."""
        if name in self._tools:
            logger.warning(f"Tool '{name}' is already registered. Overwriting.")

        self._tools[name] = Tool(name, description, func, parameters)
        logger.info(f"Tool '{name}' registered successfully.")

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

            return tool.func(**kwargs)
        except Exception as e:
            logger.exception(f"Error executing tool '{tool_name}': {e}")
            return f"Error executing tool '{tool_name}': {str(e)}"

    def _get_required_params(self, parameters: Dict[str, Any]) -> List[str]:
        """Extract required parameters from JSON schema."""
        try:
            return parameters.get("required", [])
        except Exception:
            return []

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """Get OpenAI schemas for all registered tools."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def get_map(self) -> Dict[str, Callable]:
        """Return a mapping of name to function for legacy support."""
        return {name: tool.func for name, tool in self._tools.items()}

registry = ToolRegistry()
