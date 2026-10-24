import os
import sys
import json
import logging
import tempfile
import subprocess
import time
import queue
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Any, List, Callable, NamedTuple, Optional
from openai import OpenAI
import threading
import atexit

from user_profile_manager import UserProfileManager

# --- Paths ---
SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_DIR = Path("/agent")

# Make /agent importable (same pattern as run_agent.py; see note at bottom)
sys.path.insert(0, str(AGENT_DIR))

try:
    from get_ip import get_gateway_ip
except ImportError:
    def get_gateway_ip():
        return "127.0.0.1"

try:
    from openai_error_handling import classify_api_error, Action
except ImportError:
    class Action:
        ABORT = "abort"
        RETRY = "retry"
        BACKOFF = "backoff"
    def classify_api_error(e):
        return Action.ABORT, 0.0

try:
    from internet_tools import (
        INTERNET_TOOL_DEFINITION_MAP, INTERNET_TOOL_MAP
    )
except ImportError:
    def search_internet(query: str, max_results: int = 5) -> str:
        return "Internet search is not available."
    def get_weather(location: str) -> str:
        return "Weather lookup is not available."
    INTERNET_TOOL_MAP = {}
    INTERNET_TOOL_DEFINITION_MAP = {}

from ollama_agent_tools import TOOL_MAP as BASE_TOOL_MAP, tools as BASE_TOOL_SCHEMAS

# --- .env loader (script-relative, matching run_agent.py convention) ---
def _load_dotenv(path: Path = AGENT_DIR / ".env") -> None:
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

_load_dotenv()

# --- Rich / prompt_toolkit (unchanged) ---
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
except ImportError:
    class Console:
        def print(self, msg, *args, **kwargs): print(msg)
        def rule(self, title): print(f"--- {title} ---")
    class Markdown:
        def __init__(self, text): self.text = text
    class Panel:
        def __init__(self, content, title): self.content = content
    class Table:
        def __init__(self, title): self.title = title
        def add_column(self, *a, **k): pass
        def add_row(self, *a, **k): pass
    console = Console()

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    prompt_session = PromptSession(history=FileHistory(str(Path.cwd() / ".repl_history")))
except ImportError:
    prompt_session = None

# --- Configuration ---
DEFAULT_MODEL = os.getenv("LLM_REPL_MODEL", "gemma4:e4b")
DEFAULT_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    os.getenv("LLM_BASE_URL", f"http://{get_gateway_ip()}:11434/v1"),
)
DEFAULT_API_KEY = os.getenv("LLM_REPL_API_KEY", "ollama")
LOG_FILE = Path.cwd() / "llm_repl.log"
MAX_CONTEXT_MESSAGES = 40  # was 20; 20 is tight for tool-heavy turns

# --- Logging ---
class LogQueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        try:
            self.log_queue.put(record)
        except Exception:
            self.handleError(record)

class LogQueueListener(threading.Thread):
    def __init__(self, log_queue, formatter=None):
        super().__init__()
        self.log_queue = log_queue
        self.formatter = formatter
        self.daemon = True
        self._stop_event = threading.Event()
    def stop(self):
        self._stop_event.set()
        self.log_queue.put(None)
    def run(self):
        while not self._stop_event.is_set():
            try:
                record = self.log_queue.get(timeout=1.0)
                if record is None: break
                msg = self.formatter.format(record) if self.formatter else record.getMessage()
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
                self.log_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                sys.stderr.write(f"LogQueueListener error: {e}\n")

logger = logging.getLogger("LLMRepl")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# File handler stays as is
_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

# Queue-based StreamHandler
_log_queue = queue.Queue()
_log_handler = LogQueueHandler(_log_queue)
_log_handler.setFormatter(_fmt)
logger.addHandler(_log_handler)

_log_listener = LogQueueListener(_log_queue, _fmt)
_log_listener.start()



# --- Local tools (NOTE: duplicated from ollama_agent_tools.py; see note at bottom) ---
# Map profile name → directory containing system_prompt.md
PROFILES: Dict[str, Path] = {
    'engineering': AGENT_DIR,
    # "prose": Path("/agent/prose"),
    # "research": Path("/agent/research"),
}


# Module-level job registry
JOBS: Dict[str, dict] = {}

# Watchdog
def _watchdog(job_id, timeout):
    time.sleep(timeout)
    job = JOBS.get(job_id)
    if job and job["proc"].poll() is None:
        try:
            job["proc"].kill()
        except Exception:
            pass
        logger.warning(f"{job_id} killed after {timeout}s")

# Cleanup
def _cleanup_jobs():
    for jid, j in list(JOBS.items()):
        proc = j.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
            logger.warning(f"Killed orphaned job {jid} on exit")
        f = j.get("log_f")
        if f and not f.closed:
            try:
                f.close()
            except Exception:
                pass

atexit.register(_cleanup_jobs)

# Dispatch (complete, self-contained)
def tool_dispatch_agent(task, profile="engineering", max_turns=40, timeout=1800):
    try:
        if profile not in PROFILES:
            return f"Error: unknown profile '{profile}'. Known: {sorted(PROFILES)}"

        prompt_dir = PROFILES[profile].resolve()
        src_prompt = prompt_dir / "system_prompt.md"
        if not src_prompt.exists():
            return f"Error: profile '{profile}' has no system_prompt.md at {src_prompt}"

        agent_script = AGENT_DIR / "run_agent.py"
        if not agent_script.exists():
            return f"Error: agent script not found at {agent_script}"

        workspace = Path(tempfile.mkdtemp(prefix=f"agent_run_{profile}_"))

        original_prompt = src_prompt.read_text(encoding="utf-8")
        override = (
            f"# DISPATCH OVERRIDE — read this first\n\n"
            f"Your working directory for this run is: {workspace}\n"
            f"- Write ALL output files here, using relative paths or paths under {workspace}.\n"
            f"- Do NOT write to /workspace,.\n"
            f"- plan.md, memory.md, todo.md, and all deliverables live in {workspace}.\n"
            f"- Confirm with `pwd` before writing anything.\n\n---\n\n"
        )
        system_prompt_path = workspace / "system_prompt.md"
        system_prompt_path.write_text(override + original_prompt, encoding="utf-8")

        task_path = workspace / "user_prompt.md"
        task_path.write_text(task, encoding="utf-8")
        log_path = workspace / "agent.log"

        backend = os.getenv("AGENT_BACKEND", "ollama")
        cmd = [
            sys.executable, str(agent_script),
            "--backend", backend,
            "--system-prompt", str(system_prompt_path),
            "--user-prompt", str(task_path),
            "--max-turns", str(max_turns),
            "--log-level", "INFO",
        ]
        model_override = os.getenv(f"AGENT_MODEL_{backend.upper()}") or os.getenv("AGENT_MODEL")
        if model_override:
            cmd.extend(["--model", model_override])

        log_f = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd, cwd=str(workspace), stdout=log_f, stderr=subprocess.STDOUT,
        )

        job_id = f"job_{len(JOBS) + 1}"
        JOBS[job_id] = {
            "proc": proc, "workspace": workspace, "log": log_path,
            "log_f": log_f, "closed": False,
            "start": time.time(), "timeout": timeout,
            "profile": profile, "backend": backend,
        }
        threading.Thread(target=_watchdog, args=(job_id, timeout), daemon=True).start()

        logger.info(f"dispatch_agent: {job_id} started (profile={profile}, pid={proc.pid})")
        return (
            f"Dispatched {job_id} (profile={profile}, backend={backend}). Running in background.\n"
            f"Workspace: {workspace}\n"
            f"Log: {log_path}\n"
            f"Poll with check_job('{job_id}') or list_jobs(). Do NOT block waiting.\n"
        )
    except Exception as e:
        logger.exception(f"dispatch_agent failed: {e}")
        return f"Error dispatching agent: {type(e).__name__}: {e}"

def tool_check_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        return f"Error: unknown job '{job_id}'. Known: {sorted(JOBS)}"
    proc = job["proc"]
    rc = proc.poll()
    if rc is None:
        elapsed = time.time() - job["start"]
        try:
            tail = job["log"].read_text(errors="replace")[-1500:]
        except Exception as e:
            tail = f"(could not read log: {e})"
        return (
            f"{job_id} RUNNING ({elapsed:.0f}s, profile={job['profile']})\n"
            f"Workspace: {job['workspace']}\n--- log tail ---\n{tail}"
        )
    # DONE
    if not job.get("closed"):
        try:
            job["log_f"].close()
        except Exception:
            pass
        job["closed"] = True
    try:
        files = sorted(
            str(p.relative_to(job["workspace"]))
            for p in job["workspace"].rglob("*")
            if p.is_file() and p.name not in {"system_prompt.md", "user_prompt.md", "agent.log"}
        )
    except Exception:
        files = []
    try:
        tail = job["log"].read_text(errors="replace")[-2000:]
    except Exception as e:
        tail = f"(could not read log: {e})"
    elapsed = time.time() - job["start"]
    return (
        f"{job_id} DONE rc={rc} ({elapsed:.0f}s, profile={job['profile']})\n"
        f"Workspace: {job['workspace']}\n"
        f"Files:\n  " + ("\n  ".join(files) if files else "(no output files)") + "\n"
        f"--- log tail ---\n{tail}"
    )

def tool_list_jobs():
    if not JOBS:
        return "No jobs dispatched yet."
    lines = []
    for jid, j in JOBS.items():
        rc = j["proc"].poll()
        status = "RUNNING" if rc is None else f"DONE rc={rc}"
        elapsed = time.time() - j["start"]
        lines.append(f"{jid}: {status} ({elapsed:.0f}s, profile={j['profile']})")
    return "\n".join(lines)


# --- Tool registry (Merged with base tools) ---
TOOL_MAP: Dict[str, Callable] = {
    **BASE_TOOL_MAP,
    "dispatch_agent": tool_dispatch_agent,
    "check_job": tool_check_job,
    "list_jobs": tool_list_jobs,
}

TOOL_SCHEMAS = BASE_TOOL_SCHEMAS + [
    {"type": "function", "function": {
        "name": "dispatch_agent",
        "description": (
            "Dispatch an autonomous agent to run a multi-step task in a fresh, isolated workspace. "
            "Returns IMMEDIATELY with a job ID — the work runs in the background. "
            "Use check_job(job_id) to poll for status. The task must be a complete brief: "
            "goal, constraints, and what 'done' looks like. Multiple dispatches may run concurrently."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Complete task brief."},
                "profile": {"type": "string", "description": f"One of {sorted(PROFILES)}. Default 'engineering'."},
                "max_turns": {"type": "integer", "description": "Max agent turns (default 40)."},
            },
            "required": ["task"],
        },
    }},
    {"type": "function", "function": {
        "name": "check_job",
        "description": "Check status of a dispatched job. Returns RUNNING with log tail, or DONE with exit code and output files.",
        "parameters": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    }},
    {"type": "function", "function": {
        "name": "list_jobs",
        "description": "List all dispatched jobs and their status.",
        "parameters": {"type": "object", "properties": {}},
    }},
]
# --- Tool registry ---

def _role(m) -> str:
    return m["role"] if isinstance(m, dict) else getattr(m, "role", "")

class ContextSnapshot(NamedTuple):
    """State packaging for the profiling worker."""
    user_input: str
    assistant_response: str
    history: List[Any]
    timestamp: float
    event_type: str # e.g., "turn_complete"

class ProfileWorker(threading.Thread):
    """Background worker that consumes profiling tasks and updates the user profile."""
    def __init__(self, repl: 'LLMRepl', queue: queue.Queue, batch_size=3, time_threshold=3.0):
        super().__init__(daemon=True)
        self.repl = repl
        self.queue = queue
        self.batch_size = batch_size
        self.time_threshold = time_threshold
        self._stop_event = threading.Event()
        self.batch = []

    def stop(self):
        self._stop_event.set()
        # Push a dummy item to wake up the queue.get if it's blocking
        self.queue.put(None)

    def run(self):
        logger.info("ProfileWorker thread started.")
        while not self._stop_event.is_set():
            try:
                # Wait for an item with a timeout to check for time-based batch trigger
                snapshot: Optional[ContextSnapshot] = self.queue.get(timeout=1.0)

                if snapshot is None: # Shutdown signal
                    self._process_batch()
                    break

                self.batch.append(snapshot)

                if len(self.batch) >= self.batch_size:
                    self._process_batch()

                self.queue.task_done()
            except queue.Empty:
                # If we have a partial batch and have waited long enough, process it
                if self.batch:
                    # Simple inactivity check: if the last snapshot is older than threshold
                    if time.time() - self.batch[-1].timestamp >= self.time_threshold:
                        self._process_batch()

        logger.info("ProfileWorker thread shutting down.")

    def _process_batch(self):
        if not self.batch:
            return

        logger.debug(f"ProfileWorker: Processing batch of {len(self.batch)} snapshots.")

        # For profiling, we typically care about the most recent state to avoid
        # oscillating the profile. We'll aggregate the interaction data.
        # In this implementation, we treat the batch as a series of events
        # and use the latest response as the primary driver for the profile update,
        # but we could potentially concatenate them.

        # We use the last item in the batch as the representative for the current state.
        latest = self.batch[-1]

        # Re-use the logic from the original _update_user_profile
        self.repl._perform_profile_update(latest.user_input, latest.assistant_response)

        self.batch = []

class LLMRepl:
    def __init__(self, model=DEFAULT_MODEL, base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.profile_manager = UserProfileManager()

        self.base_system_prompt = (
            "You are a helpful assistant with access to local tools. Use tools when necessary. "
            "For multi-step work that needs more than 2-3 tool calls, use dispatch_agent "
            "instead of doing it one step at a time. "
            "The dispatch_agent task must be a complete brief: goal, constraints, "
            "and what 'done' looks like."
            "The 'rich' python module is installed, so you can use markdown formatting in your responses. "
        )
        self.system_prompt = self._build_system_prompt()
        self.messages: List[Any] = [{"role": "system", "content": self.system_prompt}]

        # --- Async Profiling Setup ---
        self.profile_queue = queue.Queue()
        self.worker = ProfileWorker(self, self.profile_queue)
        self.worker.start()
        atexit.register(self.shutdown_worker)

    def shutdown_worker(self):
        logger.info("Shutting down ProfileWorker...")
        self.worker.stop()
        self.worker.join(timeout=5.0)

    def _build_system_prompt(self) -> str:
        profile_str = self.profile_manager.get_profile_string()
        return (
            f"{self.base_system_prompt}\n\n"
            f"### User Profile\n"
            f"The following is what is known about the user. Use this to personalize responses:\n"
            f"{profile_str}"
        )

    def _trim_context(self):
        """Keep system + last N messages, never starting on an orphaned tool result."""
        if len(self.messages) <= MAX_CONTEXT_MESSAGES:
            return
        keep_count = MAX_CONTEXT_MESSAGES - 1
        tail = self.messages[-keep_count:]
        while tail and _role(tail[0]) == "tool":
            tail = tail[1:]
        self.messages = [self.messages[0]] + tail
        logger.info(f"Trimmed context to {len(self.messages)} messages.")

    def _handle_api_error(self, e: Exception) -> bool:
        """Return True to continue the loop, False to abort the turn."""
        action, delay = classify_api_error(e)
        if action == Action.RETRY:
            logger.warning(f"API error: {e}. Retrying in {delay}s...")
            time.sleep(delay)
            return True
        if action == Action.BACKOFF:
            logger.warning(f"Rate limit: {e}. Backing off {delay}s...")
            time.sleep(delay)
            return True
        logger.error(f"Fatal API error: {e}")
        # Only retract the user's message if nothing was consumed yet
        if self.messages and _role(self.messages[-1]) == "user":
            self.messages.pop()
        return False

    def _perform_profile_update(self, user_input: str, assistant_response: str):
        """Internal method called by the worker to actually call the LLM and update state."""
        profile_data = self.profile_manager.profile_data

        prompt = (
            f"You are a profiling agent. Your task is to maintain a JSON profile of the user.\n"
            f"Current Profile: {json.dumps(profile_data, indent=2)}\n\n"
            f"Latest Interaction:\n"
            f"User: {user_input}\n"
            f"Assistant: {assistant_response}\n\n"
            f"Based on this interaction, update the user profile. Extract preferences, goals, technical level, "
            f"or any other useful information. Return ONLY a JSON object containing the updated profile."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": "You are a helpful assistant that outputs ONLY JSON."},
                         {"role": "user", "content": prompt}],
                tools=None,
                tool_choice=None,
            )
            content = response.choices[0].message.content
            # Simple JSON extraction
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            updated_profile = json.loads(content)
            self.profile_manager.set_profile_data(updated_profile)
            self.system_prompt = self._build_system_prompt()
            self.messages[0] = {"role": "system", "content": self.system_prompt}
            logger.debug("User profile updated successfully by worker.")
        except Exception as e:
            logger.error(f"Failed to update user profile in worker: {e}")

    def send_message(self, user_input: str):
        self.messages.append({"role": "user", "content": user_input})
        self._trim_context()
        MAX_RETRIES = 5
        retries = 0

        while True:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                )
            except Exception as e:
                if not self._handle_api_error(e):
                    break
                retries += 1
                if retries >= MAX_RETRIES:
                    console.print(f"[bold red]Max retries reached. Aborting turn.[/bold red]")
                    break
                continue

            msg = response.choices[0].message
            self.messages.append(msg)

            if not msg.tool_calls:
                if msg.content:
                    console.print(Panel(Markdown(msg.content), title="Assistant"))
                    final_response = msg.content
                else:
                    console.print("[bold red]Assistant: (No response)[/bold red]")
                    final_response = ""

                # ASYNC PROFILING: Package snapshot and put on queue
                snapshot = ContextSnapshot(
                    user_input=user_input,
                    assistant_response=final_response,
                    history=list(self.messages),
                    timestamp=time.time(),
                    event_type="turn_complete"
                )
                self.profile_queue.put(snapshot)

                break

            # Tool round: every tool_call gets exactly one tool response.
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    self.messages.append({
                        "role": "tool", "tool_call_id": tool_call.id,
                        "name": fn_name,
                        "content": f"Error: malformed JSON arguments ({e}). Retry with valid JSON.",
                    })
                    continue

                args_preview = str(args)
                if len(args_preview) > 200:
                    args_preview = args_preview[:200] + "..."
                console.print(f"[bold blue][*] Calling tool:[/bold blue] {fn_name}({args_preview})")
                logger.info(f"Tool call: {fn_name} args={args}")

                if fn_name in TOOL_MAP:
                    try:
                        result = TOOL_MAP[fn_name](**args)
                    except Exception as e:
                        result = f"Error executing tool: {e}"
                else:
                    result = f"Error: Tool {fn_name} not found."

                display = result[:500] + "..." if len(result) > 500 else result
                console.print(f"[bold green][*] Tool result:[/bold green]\n{display}")
                logger.info(f"Tool result ({len(result)} chars): {result[:1000]}")

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": fn_name,
                    "content": result,
                })

    def run(self):
        console.rule("[bold green]LLM REPL Started (Profiled V2)[/bold green]")
        console.print(
            f"Model: [bold]{self.model}[/bold] | Base URL: [bold]{self.client.base_url}[/bold]"
        )
        console.print(
            "Commands: [bold]/q[/bold] quit, [bold]/clear[/bold] reset, "
            "[bold]/sys <prompt>[/bold] set system prompt, [bold]/model <name>[/bold] change model, "
            "[bold]/history[/bold] show context, [bold]/profile[/bold] view profile"
        )

        while True:
            try:
                if prompt_session:
                    user_input = prompt_session.prompt("\nUser > ").strip()
                else:
                    user_input = input("\nUser > ").strip()

                if not user_input:
                    continue

                if user_input == "/q":
                    console.print("[bold red]Goodbye![/bold red]")
                    break
                if user_input == "/clear":
                    self.messages = [{"role": "system", "content": self.system_prompt}]
                    console.print("[yellow]Conversation history cleared.[/yellow]")
                    continue
                if user_input.startswith("/sys "):
                    self.base_system_prompt = user_input[5:].strip()
                    self.system_prompt = self._build_system_prompt()
                    self.messages = (
                        [{"role": "system", "content": self.system_prompt}]
                        + self.messages[1:]
                    )
                    console.print(f"[yellow]System prompt updated.[/yellow]")
                    continue
                if user_input.startswith("/model "):
                    self.model = user_input[7:].strip()
                    console.print(f"[yellow]Model switched to: {self.model}[/yellow]")
                    continue
                if user_input == "/profile":
                    console.print(Panel(self.profile_manager.get_profile_string(), title="User Profile"))
                    continue
                if user_input == "/history":
                    table = Table(title="Conversation History")
                    table.add_column("Role", style="cyan")
                    table.add_column("Content", style="white")
                    for m in self.messages:
                        role = _role(m)
                        content = m["content"] if isinstance(m, dict) else (getattr(m, "content", "") or "")
                        content = str(content)
                        if len(content) > 100:
                            content = content[:100] + "..."
                        table.add_row(role, content)
                    console.print(table)
                    continue

                self.send_message(user_input)
            except KeyboardInterrupt:
                console.print("\n[bold red]Goodbye![/bold red]")
                break
            except Exception as e:
                logger.exception(f"Unexpected error: {e}")
                console.print(f"[bold red]Unexpected error: {e}[/bold red]")


if __name__ == "__main__":
    repl = LLMRepl(
        model=os.getenv("LLM_REPL_MODEL", DEFAULT_MODEL),
        base_url=os.getenv("LLM_REPL_BASE_URL", DEFAULT_BASE_URL),
        api_key=os.getenv("LLM_REPL_API_KEY", DEFAULT_API_KEY),
    )
    repl.run()
