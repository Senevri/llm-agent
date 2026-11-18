from dataclasses import dataclass
from llm_utils import estimate_tokens
from typing import List, Dict, Any, Optional
from llm_utils import _role, robust_json_extract, normalize_messages
import logging
from custom_logger import setup_logging
from prompt_generator import PromptGenerator, find_prompt_dir

logger = setup_logging(__name__)

@dataclass
class TrimPlan:
    keep: List[Dict[str, Any]]          # messages to keep verbatim
    compress: List[Dict[str, Any]]      # messages to summarize
    reason: str                         # "usage" | "forced" | "none"


PROMPT_DIR = find_prompt_dir()


class Compressor:
    def __init__(self, api, max_context_messages: int = 10):
        self.api = api
        self.max_context_messages = max_context_messages
        self.prompt_gen = PromptGenerator(prompts_dir=str(PROMPT_DIR))

    def plan(self, messages: List[Dict[str, Any]], force: bool = False) -> TrimPlan:
        """Pure: no mutation of the input, no I/O."""
        usage_pct = getattr(self.api.usage, "context_pct", 0.0) or 0.0
        last_prompt = getattr(self.api.usage, "last_prompt_tokens", 0) or 0
        limit = self.api.context_limit or 8192

        if not force and usage_pct < 0.75 and last_prompt < limit * 0.80:
            return TrimPlan(keep=list(messages), compress=[], reason="none")

        keep_count = max(self.max_context_messages - 1, 3)
        tail = list(messages[-keep_count:])
        if not tail:
            return TrimPlan(keep=list(messages), compress=[], reason="none")

        while tail and _role(tail[0]) == "tool":
            tail.pop(0)

        compress: List[Dict[str, Any]] = []
        overflow_end = len(messages) - len(tail)
        compress.extend(messages[1:overflow_end])

        while tail and estimate_tokens(tail) > limit * 2 // 3:
            if _role(tail[0]) == "assistant" and tail[0].get("tool_calls"):
                group = [tail.pop(0)]
                while tail and _role(tail[0]) == "tool":
                    group.append(tail.pop(0))
                compress.extend(group)
            else:
                compress.append(tail.pop(0))

        return TrimPlan(keep=tail, compress=compress,
                        reason="forced" if force else "usage")

    def summarize(self, msgs: List[Dict[str, Any]]) -> Optional[str]:
        if not msgs:
            return None
        sections = [self._format_for_compression(m) for m in msgs]
        try:
            content = self.ai_compress(sections,
                                       max_tokens=self.api.context_limit // 3)
        except Exception as e:
            logger.error("Trim summarizer failed: %s", e)
            return None
        if not isinstance(content, str) or not content.strip():
            return None
        return content.strip()

    # keep ai_compress and _format_for_compression as-is

    def ai_compress(self, sections, max_tokens=2000):
        content = self.prompt_gen.generate_prompt("message_compression")
        content = content.replace("{max_tokens}", str(max_tokens))
        task_message = [
            {"role": "system",
             "content": content},
            {"role": "user", "content": "\n\n".join(sections[:-1])}]

        response =  self.api.client.chat.completions.create(
                model=self.api.model,
                messages=normalize_messages(task_message, self.api.backend)
            )
        return response.choices[0].message.content




    def _format_for_compression(self, msg: dict) -> str:
        if msg.get("role") == "tool":
            return f"[TOOL RESULT: {msg.get('name', 'unknown')} (ID: {msg.get('tool_call_id')})]\n{msg.get('content')}"
        return f"{msg['role']}: {msg.get('content', '')}"
