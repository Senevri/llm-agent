from dataclasses import dataclass
from llm_utils import estimate_tokens
from typing import List, Dict, Any, Optional
from llm_utils import _role, robust_json_extract, normalize_messages, _relative_paths_helper
import logging
from custom_logger import setup_logging
from prompt_generator import PromptGenerator, find_prompt_dir
import secrets
from pprint import pformat


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

    def plan(self, messages, force=False) -> TrimPlan:
        usage_pct = getattr(self.api.usage, "context_pct", 0.0) or 0.0
        limit = self.api.context_limit or 8192
        messages = normalize_messages(messages, self.api.backend)

        if not force and usage_pct < 80:
            return TrimPlan(keep=list(messages), compress=[], reason="none")
        if not messages:
            return TrimPlan(keep=[], compress=[], reason="none")

        # the final turn must survive whole, even under a tiny budget
        floor = len(messages) - 1
        while floor > 0 and _role(messages[floor]) == "tool":
            floor -= 1

        keep_count = max(self.max_context_messages - 1, 3)
        split = max(len(messages) - keep_count, 0)
        split = min(split, floor)

        budget = limit * 2 // 3
        while split < floor and estimate_tokens(messages[split:]) > budget:
            nxt = split + 1
            if _role(messages[split]) == "assistant" and messages[split].get("tool_calls"):
                while nxt < len(messages) and _role(messages[nxt]) == "tool":
                    nxt += 1
            split = min(nxt, floor)

        # never begin the kept tail with an orphaned tool result
        while split < floor and _role(messages[split]) == "tool":
            split += 1

        if split >= len(messages):
            split = floor

        compress, keep = list(messages[:split]), list(messages[split:])
        out, keep = self._repair_keep(keep)
        compress.extend(out)
        if not compress:
            return TrimPlan(keep=keep, compress=[], reason="none")
        return TrimPlan(keep=keep, compress=compress,
                        reason="forced" if force else "usage")

    def _repair_keep(self, keep):
        out = []
        i = 0
        while i < len(keep):
            m = keep[i]
            if _role(m) == "assistant" and m.get("tool_calls"):
                needed = {tc["id"] for tc in m["tool_calls"]}
                j = i + 1
                seen = set()
                while j < len(keep) and _role(keep[j]) == "tool":
                    if keep[j].get("tool_call_id") in needed:
                        seen.add(keep[j]["tool_call_id"])
                    j += 1
                if seen != needed:
                    # incomplete group → push this assistant (and any partial tools)
                    # into compress instead of keeping it
                    return out, keep[i:]      # caller extends compress
                out.extend(keep[i:j])
                i = j
            else:
                out.append(m); i += 1
        return out, []

    def truncate_tool_results(self, t_id, messages, max_tool_results, tool_logger):
        # generate hash
        tool_results = messages.copy()
        result_length = estimate_tokens(tool_results)
        _mtr = max_tool_results

        # msg was warning; changed to info since it _currently works_
        logger.info(
            "Tool results too long %s",
            pformat([t for t in tool_results])
            )
        max_result_per_msg = _mtr // len(tool_results)
        # truncate tool results
        for i, result in enumerate(tool_results):
            result["content"] = (
                f"Tool output truncated; original: {result_length} tokens. "
                f"see {_relative_paths_helper(tool_logger.log_file)} for " # type: ignore
                f"full output. tag: {t_id}\n"
                f"{result.to_message(max_result_per_msg).get('content')}"
                )
            tool_results[i] = result
        return tool_results


    def _combine_contents_by_role(self, messages) -> List:
        # Fast path: nothing to combine
        if len(messages) < 2:
            return messages
        if not any(
            _role(a) == _role(b)
            and _role(a) in ("assistant", "user")
            and a.get("content")
            and b.get("content")
            for a, b in zip(messages, messages[1:])
        ):
            return messages

        prev_msg = messages[0].copy()
        new_msg_queue = []
        for original_msg in messages[1:]:
            msg = original_msg.copy()
            if (
                _role(msg) in ["assistant", "user"]
                and prev_msg.get("content")
                and msg.get("content")
                and _role(msg) == _role(prev_msg)
                ):
                msg["content"] = prev_msg.get("content") + "\n" + msg["content"]
                mergeables = ["tool_calls", "reasoning_content"]
                for mrg in mergeables:
                    if msg.get(mrg) or prev_msg.get(mrg):
                        logger.warning(f"--- Merging {mrg}! ---\n{msg}")
                        msg[mrg] = (prev_msg.get(mrg) or []) + (msg.get(mrg) or [])
            else:
                new_msg_queue.append(prev_msg)
            prev_msg = msg
        # append final
        new_msg_queue.append(prev_msg)
        return new_msg_queue





    # def _plan(self, messages: List[Dict[str, Any]], force: bool = False) -> TrimPlan:
    #     """Pure: no mutation of the input, no I/O."""
    #     usage_pct = getattr(self.api.usage, "context_pct", 0.0) or 0.0
    #     # last_prompt = getattr(self.api.usage, "last_prompt_tokens", 0) or 0
    #     limit = self.api.context_limit or 8192

    #     messages = normalize_messages(messages, self.api.backend)

    #     if not force and usage_pct < 80:
    #         return TrimPlan(keep=list(messages), compress=[], reason="none")

    #     keep_count = max(self.max_context_messages - 1, 3)
    #     tail = list(messages[-keep_count:])
    #     if not tail:
    #         return TrimPlan(keep=list(messages), compress=[], reason="none")

    #     compress: List[Dict[str, Any]] = []

    #     while tail and _role(tail[0]) == "tool":
    #         compress.append(tail.pop(0))



    #     overflow_end = len(messages) - len(tail)
    #     compress.extend(messages[1:overflow_end])
    #     while tail and estimate_tokens(tail) > limit * 2 // 3:

    #         if _role(tail[0]) == "assistant" and tail[0].get("tool_calls"):
    #             group = [tail.pop(0)]
    #             while tail and _role(tail[0]) == "tool":
    #                 group.append(tail.pop(0))
    #             compress.extend(group)
    #         else:
    #             compress.append(tail.pop(0))

    #     return TrimPlan(keep=tail, compress=compress,
    #                     reason="forced" if force else "usage")

    def summarize(self, msgs: List[Dict[str, Any]]) -> Optional[str]:
        max_tokens=(self.api.context_limit or 8192) // 3
        if not msgs:
            return None
        sections = [self._format_for_compression(m) for m in msgs]
        try:
            content = self.ai_compress(sections,
                                       max_tokens=max_tokens)
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
            {"role": "user", "content": "\n\n".join(sections)}]

        # ai_compress(): actually bound the response
        response = self.api.client.chat.completions.create(
            model=self.api.model,
            messages=normalize_messages(task_message, self.api.backend),
            max_tokens=max_tokens,
            )
        return response.choices[0].message.content


    def _format_for_compression(self, msg: dict) -> str:
        role = msg.get("role", "unknown")
        if role == "tool":
            return (f"[TOOL RESULT: {msg.get('name', 'unknown')} "
                    f"(ID: {msg.get('tool_call_id')})]\n{msg.get('content') or ''}")
        lines = []
        content = msg.get("content") or ""
        if content.strip():
            lines.append(f"{role}: {content}")
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {}) or {}
            lines.append(f"[TOOL CALL: {fn.get('name')} (ID: {tc.get('id')}) "
                        f"args={fn.get('arguments')}]")
        return "\n".join(lines) if lines else f"{role}: (empty)"

    def old_format_for_compression(self, msg: dict) -> str:
        if msg.get("role") == "tool":
            return f"[TOOL RESULT: {msg.get('name', 'unknown')} (ID: {msg.get('tool_call_id')})]\n{msg.get('content')}"
        return f"{msg['role']}: {msg.get('content', '')}"
