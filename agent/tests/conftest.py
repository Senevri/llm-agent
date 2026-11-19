import copy, types, pathlib
import pytest, yaml

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_messages(name="conio2hack.yaml"):
    return yaml.safe_load((FIXTURES / name).read_text())


def tag(msgs):
    """Stable identity per message so we can track loss / order / duplication."""
    out = []
    for i, m in enumerate(msgs):
        m = dict(m)
        m["_uid"] = i
        out.append(m)
    return out


def uids(msgs):
    return [m["_uid"] for m in msgs if "_uid" in m]


def repeat_turns(base, n):
    """Grow a realistic transcript, keeping tool_call ids unique and paired."""
    out = []
    for k in range(n):
        for m in base:
            m = copy.deepcopy(m)
            for tc in (m.get("tool_calls") or []):
                tc["id"] = f"{tc['id']}-{k}"
            if m.get("tool_call_id"):
                m["tool_call_id"] = f"{m['tool_call_id']}-{k}"
            if m.get("role") == "tool":
                m["content"] = (m.get("content") or "") + ("\n" + "x" * 200)
            out.append(m)
    return out


class FakeUsage:
    def __init__(self, pct=0.0):
        self.context_pct = pct
        self.last_prompt_tokens = 0


class FakeCompletions:
    def __init__(self, reply="SUMMARY"):
        self.reply = reply
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        msg = types.SimpleNamespace(content=self.reply)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


class FakeAPI:
    def __init__(self, pct=0.0, limit=8192, reply="SUMMARY", backend="openai"):
        self.usage = FakeUsage(pct)
        self.context_limit = limit
        self.backend = backend
        self.model = "test-model"
        self.completions = FakeCompletions(reply)
        self.client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=self.completions))


@pytest.fixture
def api():
    return FakeAPI(pct=95.0, limit=8192)