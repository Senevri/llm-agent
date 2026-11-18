import unittest
from unittest.mock import MagicMock, patch
import json
import threading
import time
import queue
from pathlib import Path
from llm_repl_profiled_v2 import LLMRepl, UserProfileManager, ContextSnapshot, ProfileError

class TestLLMReplV2(unittest.TestCase):
    def setUp(self):
        self.patcher = patch('llm_repl_profiled_v2.OpenAI')
        self.mock_openai_class = self.patcher.start()
        self.mock_client = self.mock_openai_class.return_value
        self.repl = LLMRepl(model="test-model")

    def tearDown(self):
        self.repl.shutdown()
        self.patcher.stop()

    def test_lock_serialization_messages_single_thread(self):
        def side_effect(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Response"
            mock_response.choices[0].message.tool_calls = None
            return mock_response
            
        self.mock_client.chat.completions.create.side_effect = side_effect
        
        for i in range(10):
            self.repl.send_message(f"msg {i}")
        
        self.assertEqual(len(self.repl.messages), 21)

if __name__ == "__main__":
    unittest.main()
