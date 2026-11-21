from queue import Queue
from dataclasses import dataclass, field
from typing import Any

@dataclass
class UIMessage:
    kind: str
    content: Any
    style: str | None = None
    end: str = "\n" # Hacky
    #kwargs: field(default_factory=dict, default=None)


class UIMessageQueue:
    def __init__(self):
        self.queue = Queue()

    def post(self, content, kind="print", style=None, **kwargs):
        self.queue.put(UIMessage(kind, content, style, **kwargs))

    def drain(self):
        while not self.queue.empty():
            yield self.queue.get()
