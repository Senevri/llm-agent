import pytest
from unittest.mock import MagicMock, patch
import run_ollama_agent_v2

def test_agent_loop_full_mock(mocker):
    # Mock OpenAI client
    mock_client = mocker.patch('run_ollama_agent_v2.client')
    
    # Mock prompt files
    mocker.patch('builtins.open', mocker.mock_open(read_data="mock prompt"))
    
    # Setup mock responses
    # Turn 1: Agent wants to call run_bash
    mock_response_1 = MagicMock()
    mock_msg_1 = MagicMock()
    mock_tool_call_1 = MagicMock()
    mock_tool_call_1.function.name = "run_bash"
    mock_tool_call_1.function.arguments = '{"command": "echo hello"}'
    mock_tool_call_1.id = "call_1"
    
    mock_msg_1.tool_calls = [mock_tool_call_1]
    mock_msg_1.content = None
    mock_response_1.choices = [MagicMock(message=mock_msg_1)]
    
    # Turn 2: Agent gives final response
    mock_response_2 = MagicMock()
    mock_msg_2 = MagicMock()
    mock_msg_2.tool_calls = None
    mock_msg_2.content = "I have finished the task."
    mock_response_2.choices = [MagicMock(message=mock_msg_2)]
    
    mock_client.chat.completions.create.side_effect = [mock_response_1, mock_response_2]
    
    # Mock tool execution to avoid real bash calls
    mocker.patch('run_ollama_agent_v2.run_bash', return_value="hello")
    
    # Execute main
    run_ollama_agent_v2.main()
    
    # Verify interactions
    assert mock_client.chat.completions.create.call_count == 2
