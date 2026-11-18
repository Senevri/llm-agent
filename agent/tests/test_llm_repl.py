import unittest
from unittest.mock import MagicMock, patch
import json
import os
from agent.llm_repl import LLMRepl, tool_run_bash, tool_read_file, tool_write_file

class TestLLMRepl(unittest.TestCase):
    def setUp(self):
        # Use a dummy model and base_url
        self.repl = LLMRepl(model="test-model", base_url="http://test:11434/v1", api_key="test-key")

    @patch('llm_repl.OpenAI')
    def test_send_message_no_tool(self, mock_openai_class):
        # Mock the client instance
        mock_client = mock_openai_class.return_value

        # Mock the response object
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello! How can I help you?"
        mock_choice.message.tool_calls = None
        mock_response.choices = [mock_choice]

        mock_client.chat.completions.create.return_value = mock_response

        # Need to re-instantiate the repl to use the mocked OpenAI class if the client was already created
        self.repl.client = mock_client

        with patch('builtins.print') as mock_print:
            self.repl.send_message("Hi")
            # Check if the correct response was printed
            mock_print.assert_any_call("\nAssistant: Hello! How can I help you?")

    @patch('llm_repl.OpenAI')
    def test_send_message_with_tool(self, mock_openai_class):
        mock_client = mock_openai_class.return_value

        # First response: tool call
        mock_res1 = MagicMock()
        mock_choice1 = MagicMock()
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "list_files"
        mock_tool_call.function.arguments = json.dumps({"path": "."})
        mock_choice1.message.content = None
        mock_choice1.message.tool_calls = [mock_tool_call]
        mock_res1.choices = [mock_choice1]

        # Second response: final answer
        mock_res2 = MagicMock()
        mock_choice2 = MagicMock()
        mock_choice2.message.content = "I see the files here."
        mock_choice2.message.tool_calls = None
        mock_res2.choices = [mock_choice2]

        mock_client.chat.completions.create.side_effect = [mock_res1, mock_res2]

        self.repl.client = mock_client

        with patch('builtins.print') as mock_print:
            # Patch the tool function in the TOOL_MAP
            with patch('llm_repl.tool_list_files') as mock_tool:
                # Update the TOOL_MAP to use our mock tool for this test
                import agent.llm_repl as llm_repl
                original_tool = llm_repl.TOOL_MAP["list_files"]
                llm_repl.TOOL_MAP["list_files"] = mock_tool

                mock_tool.return_value = "file1.txt\nfile2.txt"
                try:
                    self.repl.send_message("What files are here?")
                    mock_tool.assert_called_once_with(path=".")
                    mock_print.assert_any_call("\nAssistant: I see the files here.")
                finally:
                    llm_repl.TOOL_MAP["list_files"] = original_tool

    @patch('llm_repl.OpenAI')
    def test_send_message_with_search_tool(self, mock_openai_class):
        mock_client = mock_openai_class.return_value

        # First response: tool call
        mock_res1 = MagicMock()
        mock_choice1 = MagicMock()
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_search"
        mock_tool_call.function.name = "search_internet"
        mock_tool_call.function.arguments = json.dumps({"query": "what is the weather in London?"})
        mock_choice1.message.content = None
        mock_choice1.message.tool_calls = [mock_tool_call]
        mock_res1.choices = [mock_choice1]

        # Second response: final answer
        mock_res2 = MagicMock()
        mock_choice2 = MagicMock()
        mock_choice2.message.content = "The weather in London is sunny."
        mock_choice2.message.tool_calls = None
        mock_res2.choices = [mock_choice2]

        mock_client.chat.completions.create.side_effect = [mock_res1, mock_res2]

        self.repl.client = mock_client

        with patch('builtins.print') as mock_print:
            with patch('llm_repl.search_internet') as mock_search:
                import agent.llm_repl as llm_repl
                original_tool = llm_repl.TOOL_MAP["search_internet"]
                llm_repl.TOOL_MAP["search_internet"] = mock_search

                mock_search.return_value = "1. Sunny\nSnippet: London is sunny\nURL: http://weather.com"
                try:
                    self.repl.send_message("What is the weather in London?")
                    mock_search.assert_called_once_with(query="what is the weather in London?")
                    mock_print.assert_any_call("\nAssistant: The weather in London is sunny.")
                finally:
                    llm_repl.TOOL_MAP["search_internet"] = original_tool

    def test_tool_run_bash(self):
        res = tool_run_bash("echo 'hello'")
        self.assertIn("hello", res)

    def test_tool_read_write_file(self):
        test_file = "test_read_write_v2.txt"
        content = "Hello World"
        tool_write_file(test_file, content)
        try:
            res = tool_read_file(test_file)
            self.assertEqual(res, content)
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
