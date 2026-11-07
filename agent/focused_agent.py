#!/usr/bin/env python3
# coding=utf-8
"""
Basic idea: Focus on a single task at a time
+ a verifable end condition.
"""
from backend import LLMBackend
from enum import Enum
from typing import List, Dict, Any
import os
from pathlib import Path

from llm_utils import normalize_messages, estimate_tokens, size_bytes
from custom_logger import setup_logging

LOG_DIR = os.getenv("LOG_DIR", "./logs/")

logger = setup_logging("FocusedAgent", level="INFO", log_dir=Path(LOG_DIR))


# from agent.loop_task import LoopTask


# class FocusedLoopTask(LoopTask):

class TodoStatus(Enum):
    TODO = 0
    DONE = 1
    ABORT = 2

class TodoItem():
    def __init__(self, name, description, test):
        self.name = name
        self.description = description
        self.status = TodoStatus.TODO
        self.completion_test = None

    def test_result(self,result):
        if callable(self.completion_test):
            return self.completion_test(result)
        else:
            return result


class FocusedLoopTask():

    def __init__(self, backend="mistral"):
        self.api = LLMBackend(backend=backend)
        self.todo = []
        self.notools = True
        self.todoitem = None
        self.messages = []
        # no skills either by default?

    def add_task(self, name, description, test):
        self.todo.append(TodoItem(name, description, test))

    def add_inputs(self, inputs):
        # TODO: format?
        self.messages.append({"role": "user", "content": inputs})

    def run_client(self):
        client, model = self.api.get_client()
        return client

    def run_turn(self):
        # Now, what are th actual inputs, outputs etc?`
        #
        # TODO: format?
        assert self.todoitem
        self.messages.append({"role": "user", "content": self.todoitem.description})

        result = self._request_chat_completion(self.messages)

        self.messages.append({"role": "assistant", "content": self.todoitem.test_result(result)})

        return result

    def _request_chat_completion(self, messages: List[Dict[str, Any]], tools=None, tool_choice=None):
        if self.notools or os.getenv("BITNET", "0") == "1":
            return self.api.client.chat.completions.create(
                model=self.api.model,
                messages=normalize_messages(messages, self.api.backend)
            )

        return self.api.client.chat.completions.create(
            model=self.api.model,
            messages=normalize_messages(messages, self.api.backend),
            tools=tools or [],
            tool_choice=tool_choice or "auto",
        )

    def start(self):
        for todoitem in self.todo:
            self.todoitem = todoitem # Track current item
            while self.todoitem and self.todoitem.status == TodoStatus.TODO:
                result = self.run_turn()
                if self.todoitem.status == TodoStatus.ABORT:
                    break
                elif self.todoitem.status == TodoStatus.DONE:
                    break




def main(args):
    task = FocusedLoopTask(args.backend)

if __name__ == "__main__":
    import sys
    import os
    import argparse
    from pathlib import Path

    sys.path.append(Path(__file__).parent.parent.as_posix())

    from dotenv import load_dotenv
    load_dotenv()

    DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "ollama")

    parser = argparse.ArgumentParser(description="Run LLM REPL")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help="LLM backend to use")
    args = parser.parse_args()

    main(args)