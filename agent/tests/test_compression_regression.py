"""Regression tests for Compressor.plan / summarize and _trim_context."""
import copy
import pytest

from compressor import Compressor, TrimPlan
from conftest import FakeAPI, load_messages, repeat_turns, tag, uids


class Repl:
    """Verbatim copy of the caller, so we test the integration too."""
    def __init__(self, api):
        self.api = api

    def _trim_context(self, messages, force: bool = False) -> dict:
        protected_count = 2
        snapshot = list(messages[protected_count:])
        anchor = protected_count + len(snapshot)

        compressor = Compressor(self.api, 40)
        plan = compressor.plan(snapshot, force=force)
        if plan.reason == "none" or not plan.compress:
            return {"messages": messages, "removed_sections": []}

        summary = compressor.summarize(plan.compress)
        if not summary:
            return {"messages": messages, "removed_sections": []}

        summary_msg = {
            "role": "assistant",
            "content": f"Historical context summary - not a new response: {summary}",
        }
        new_tail = messages[anchor:]
        new_messages = [messages[0], messages[1], summary_msg, *plan.keep, *new_tail]
        return {"messages": new_messages, "removed_sections": plan.compress}


def transcript(n=12):
    body = repeat_turns(load_messages()[1:], n)
    return [{"role": "system", "content": "you are a helpful agent"},
            {"role": "user", "content": "refactor the C project"}] + body


def assert_well_formed(msgs):
    """Every tool result must follow the assistant that requested it."""
    open_ids = set()
    for m in msgs:
        if m.get("role") == "assistant":
            open_ids = {tc["id"] for tc in (m.get("tool_calls") or [])}
        elif m.get("role") == "tool":
            cid = m.get("tool_call_id")
            assert cid in open_ids, f"orphaned tool result {cid}"


# ------------------------------------------------------------- no-op paths
def test_below_threshold_is_noop():
    msgs = tag(transcript(3))
    plan = Compressor(FakeAPI(pct=10.0), 40).plan(msgs)
    assert plan.reason == "none"
    assert plan.compress == []
    assert uids(plan.keep) == uids(msgs)


def test_force_on_short_history_is_noop():
    msgs = tag(transcript(1))
    plan = Compressor(FakeAPI(pct=0.0), 40).plan(msgs, force=True)
    assert plan.compress == []
    assert uids(plan.keep) == uids(msgs)


def test_empty_input():
    plan = Compressor(FakeAPI(pct=99.0), 40).plan([], force=True)
    assert plan.keep == [] and plan.compress == []


def test_plan_does_not_mutate_input():
    msgs = transcript(12)
    before = copy.deepcopy(msgs)
    Compressor(FakeAPI(pct=95.0), 40).plan(msgs, force=True)
    assert msgs == before, "plan() promised purity"


# -------------------------------------------------------- conservation laws
def test_no_message_is_silently_dropped():
    """keep + compress must account for every input message."""
    msgs = tag(transcript(12))
    plan = Compressor(FakeAPI(pct=95.0), 40).plan(msgs, force=True)
    accounted = set(uids(plan.keep)) | set(uids(plan.compress))
    missing = set(uids(msgs)) - accounted
    assert not missing, f"messages vanished from keep AND compress: {sorted(missing)}"


def test_no_message_is_duplicated():
    msgs = tag(transcript(12))
    plan = Compressor(FakeAPI(pct=95.0), 40).plan(msgs, force=True)
    seen = uids(plan.keep) + uids(plan.compress)
    dupes = {u for u in seen if seen.count(u) > 1}
    assert not dupes, f"duplicated messages: {sorted(dupes)}"


def test_compress_is_chronological():
    msgs = tag(transcript(12))
    plan = Compressor(FakeAPI(pct=95.0), 40).plan(msgs, force=True)
    got = uids(plan.compress)
    assert got == sorted(got), f"summary built from scrambled transcript: {got}"


def test_snapshot_starting_with_tool_result():
    """_trim_context slices at index 2, which is often a tool result."""
    full = transcript(12)
    cut = next(i for i, m in enumerate(full) if m["role"] == "tool")
    msgs = tag(full[cut:])
    assert msgs[0]["role"] == "tool"
    plan = Compressor(FakeAPI(pct=95.0), 40).plan(msgs, force=True)
    seen = uids(plan.compress)
    dupes = {u for u in seen if seen.count(u) > 1}
    assert not dupes, f"duplicated: {sorted(dupes)}"
    assert seen == sorted(seen), f"out of order: {seen}"


def test_keep_is_well_formed():
    plan = Compressor(FakeAPI(pct=95.0), 40).plan(transcript(12), force=True)
    assert plan.keep, "keep must never be empty"
    assert_well_formed(plan.keep)


def test_keep_is_a_suffix_of_the_input():
    msgs = tag(transcript(12))
    plan = Compressor(FakeAPI(pct=95.0), 40).plan(msgs, force=True)
    assert uids(plan.keep) == uids(msgs)[-len(plan.keep):]


def test_tiny_context_limit_still_keeps_something():
    msgs = tag(transcript(12))
    plan = Compressor(FakeAPI(pct=95.0, limit=64), 40).plan(msgs, force=True)
    assert plan.keep, "budget loop drained the entire tail"
    assert_well_formed(plan.keep)


# --------------------------------------------------------- summary content
def test_tool_call_arguments_survive_compression():
    """This transcript carries its meaning in tool_calls, not in content."""
    api = FakeAPI(pct=95.0)
    c = Compressor(api, 40)
    msgs = load_messages()
    c.summarize([m for m in msgs if m["role"] == "assistant"])
    sent = api.completions.calls[0]["messages"][-1]["content"]
    assert "conio2hack" in sent, "paths inside tool_calls dropped from summary input"
    assert "list_files" in sent, "tool names dropped from summary input"


def test_assistant_tool_calls_are_not_summarized_as_blank():
    c = Compressor(FakeAPI(), 40)
    msg = load_messages()[1]
    assert c._format_for_compression(msg).strip() != "assistant:", \
        "assistant turn with tool_calls formatted as an empty string"


def test_max_tokens_is_forwarded_to_the_api():
    api = FakeAPI(pct=95.0, limit=9000)
    Compressor(api, 40).summarize(load_messages())
    kwargs = api.completions.calls[0]
    assert kwargs.get("max_tokens") == 3000, f"max_tokens never sent: {list(kwargs)}"


def test_none_context_limit_does_not_silently_disable_trimming():
    api = FakeAPI(pct=95.0, limit=None)
    assert Compressor(api, 40).summarize(load_messages()) == "SUMMARY"


def test_summarizer_failure_returns_none():
    api = FakeAPI(pct=95.0, reply=None)
    assert Compressor(api, 40).summarize(load_messages()) is None


def test_summarize_empty_returns_none():
    assert Compressor(FakeAPI(), 40).summarize([]) is None


# ------------------------------------------------------------- integration
def test_trim_context_conserves_every_message():
    api = FakeAPI(pct=95.0)
    msgs = tag(transcript(12))
    out = Repl(api)._trim_context(msgs, force=True)
    kept, removed = uids(out["messages"]), uids(out["removed_sections"])
    missing = set(uids(msgs)) - (set(kept) | set(removed))
    assert not missing, f"_trim_context lost messages: {sorted(missing)}"


def test_trim_context_output_is_well_formed():
    api = FakeAPI(pct=95.0)
    out = Repl(api)._trim_context(transcript(12), force=True)
    assert out["messages"][0]["role"] == "system"
    assert out["messages"][1]["role"] == "user"
    assert_well_formed(out["messages"][2:])


def test_trim_context_actually_shrinks_context():
    api = FakeAPI(pct=95.0)
    msgs = transcript(12)
    out = Repl(api)._trim_context(msgs, force=True)
    assert len(out["messages"]) < len(msgs), "trim was a no-op"


def test_trim_context_noop_below_threshold():
    msgs = transcript(12)
    out = Repl(FakeAPI(pct=10.0))._trim_context(msgs)
    assert out["messages"] is msgs
    assert out["removed_sections"] == []