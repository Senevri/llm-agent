import unittest
from unittest.mock import MagicMock, patch
from llm_repl_profiled import LLMRepl

class TestLLMReplProfiling(unittest.TestCase):
    @patch('llm_repl_profiled.OpenAI')
    @patch('llm_repl_profiled.UserProfileManager')
    def test_profile_integration(self, mock_upm_class, mock_openai_class):
        # Setup mocks
        mock_upm = mock_upm_class.return_value
        mock_upm.profile_data = {"name": "Bob"}
        mock_upm.get_profile_string.return_value = '{"name": "Bob"}'
        
        mock_client = mock_openai_class.return_value
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"name": "Bob", "likes": "Python"}'
        mock_response.choices[0].message.tool_calls = None
        mock_client.chat.completions.create.return_value = mock_response
        
        repl = LLMRepl()
        
        # Test system prompt contains profile
        self.assertIn('{"name": "Bob"}', repl.system_prompt)
        
        # Test profiling call after send_message
        # We need to mock the response for the first call (send_message) 
        # and the second call (_update_user_profile)
        mock_client.chat.completions.create.side_effect = [
            mock_response, # response to user message
            mock_response  # response to profiling prompt
        ]
        
        # Mock console.print to avoid pollution
        with patch('llm_repl_profiled.console.print'):
            repl.send_message("Hello, I love Python!")
        
        # Check if profile update was called
        # 2nd call to create should be the profiling one
        args, kwargs = mock_client.chat.completions.create.call_args_list[1]
        self.assertIn("You are a profiling agent", kwargs['messages'][1]['content'])
        
        # Check if profile manager was updated
        mock_upm.set_profile_data.assert_called()

if __name__ == "__main__":
    unittest.main()
