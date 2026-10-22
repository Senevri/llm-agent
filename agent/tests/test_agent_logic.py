import pytest
from unittest.mock import MagicMock, patch
import json
import run_ollama_agent_v2

def test_tool_dispatching(mocker):
    # We need to patch the function inside the TOOL_MAP dictionary, 
    # or patch the original function and ensure TOOL_MAP is updated or uses the patched version.
    # Since TOOL_MAP = {"run_bash": run_bash, ...}, it holds a reference to the function.
    # Patching run_ollama_agent_v2.run_bash after the module is loaded doesn't update the reference in TOOL_MAP.
    
    # Solution: Directly patch the dictionary entry or patch the function before TOOL_MAP is created (harder here).
    mock_func = MagicMock(return_value="mocked bash output")
    run_ollama_agent_v2.TOOL_MAP["run_bash"] = mock_func
    
    # Create a mock tool call
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "run_bash"
    mock_tool_call.function.arguments = json.dumps({"command": "ls -la"})
    mock_tool_call.id = "call_123"
    
    # Simulate the logic inside the main loop for tool execution
    func_name = mock_tool_call.function.name
    if func_name in run_ollama_agent_v2.TOOL_MAP:
        args = json.loads(mock_tool_call.function.arguments)
        result = run_ollama_agent_v2.TOOL_MAP[func_name](**args)
    else:
        result = "Unknown tool"
        
    assert result == "mocked bash output"
    mock_func.assert_called_once_with(command="ls -la")
    
    # Restore TOOL_MAP
    from run_ollama_agent_v2 import run_bash
    run_ollama_agent_v2.TOOL_MAP["run_bash"] = run_bash

def test_context_trimming():
    limit = run_ollama_agent_v2.CONTEXT_WINDOW_LIMIT
    messages = [{"role": "system", "content": "sys"}] + [{"role": "user", "content": f"msg{i}"} for i in range(limit + 5)]
    
    if len(messages) > limit + 1:
        messages = [messages[0]] + messages[-(limit):]
    
    assert len(messages) == limit + 1
    assert messages[0]["role"] == "system"
    assert messages[-1]["content"] == f"msg{limit + 4}"
