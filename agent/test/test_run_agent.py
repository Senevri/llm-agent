import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Add current directory and /agent to path
sys.path.append('/agent')
sys.path.append(os.getcwd())

import run_agent

class TestRunAgent(unittest.TestCase):
    def test_get_client_ollama(self):
        """Test that Ollama client is created correctly."""
        with patch('run_agent.get_gateway_ip', return_value="127.0.0.1"):
            client, model = run_agent.get_client("ollama")
            self.assertIsNotNone(client)
            self.assertEqual(model, os.getenv("AGENT_MODEL", "gemma4:31b-cloud"))

    def test_get_client_mistral_no_key(self):
        """Test that Mistral client raises error if key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                run_agent.get_client("mistral")
            self.assertIn("MISTRAL_API_KEY not set", str(cm.exception))

    def test_get_client_mistral_with_key(self):
        """Test that Mistral client is created when key is present."""
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test_key"}):
            client, model = run_agent.get_client("mistral")
            self.assertIsNotNone(client)
            self.assertEqual(model, os.getenv("AGENT_MODEL", "ministral-14b-latest"))

    def test_trim_messages(self):
        """Test the message trimming logic."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "tool", "content": "t1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "tool", "content": "t2"},
        ]
        # Limit 2: system + last 2. 
        # Since last 2 are assistant/tool or tool/user... 
        # Wait, if last one is tool, it's kept. If the first of the tail is tool, it's dropped.
        trimmed = run_agent._trim_messages(messages, 2)
        self.assertEqual(trimmed[0]["role"], "system")
        # The tail is [ {"role": "assistant", "content": "a2"}, {"role": "tool", "content": "t2"} ]
        # _role(tail[0]) is "assistant", so it stays.
        self.assertEqual(len(trimmed), 3)
        self.assertEqual(trimmed[-1]["content"], "t2")

    def test_trim_messages_drop_orphaned_tool(self):
        """Test that orphaned tool messages at the start of the tail are dropped."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "tool", "content": "t1"}, # This should be dropped if it's the first of the tail
            {"role": "user", "content": "u2"},
        ]
        # limit 2: system + last 2. tail = [{"role": "tool", "content": "t1"}, {"role": "user", "content": "u2"}]
        # Since tail[0] is "tool", it is dropped.
        trimmed = run_agent._trim_messages(messages, 2)
        self.assertEqual(len(trimmed), 2) 
        self.assertEqual(trimmed[0]["role"], "system")
        self.assertEqual(trimmed[1]["role"], "user")

if __name__ == "__main__":
    unittest.main()
