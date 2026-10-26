import os
import re
import sys
import shlex
import logging
import tempfile
import subprocess
import time
import uuid
import errno
import signal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("AgentDispatcher")

# Env vars forwarded into the tmux session (an existing tmux server won't inherit ours).
FORWARD_ENV = (
    "AGENT_BACKEND", "AGENT_MODEL", "AGENT_DIR", "AGENT_LOG_LEVEL",
    "OLLAMA_PORT", "OLLAMA_BASE_URL", "MISTRAL_API_KEY", "MISTRAL_BASE_URL",
    "PYTHONPATH",
)
SESSION_RE = re.compile(r"[A-Za-z0-9_-]+")  # tmux dislikes '.' and ':' in names


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=15)

def _get_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

class AgentDispatcher:
    def __init__(self, agent_dir: Optional[str] = None, prompt_gen=None):
        self.agent_dir = Path(agent_dir or os.environ.get("AGENT_DIR", "/agent"))
        self.prompt_gen = prompt_gen
        self.backend = os.getenv("AGENT_BACKEND", "mistral")
        self.active_jobs: Dict[str, Dict[str, Any]] = {}

    # ---------- launching ----------

    @staticmethod
    def _write_wrapper(workspace: Path, cmd: list[str], timeout: int) -> Path:
        """Wrapper: run the agent, tee output to agent.log, record exit code."""
        path = workspace / "run_wrapper.sh"
        path.write_text(
            "#!/bin/bash\n"
            f"cd {shlex.quote(str(workspace))} || exit 125\n"
            'echo "$$" > process_group_id\n'
            "export PYTHONUNBUFFERED=1\n"
            'log() { echo "[$(date -Is)] $*" | tee -a agent.log; }\n'
            'log "starting agent"\n'
            f"timeout --foreground --signal=TERM --kill-after=10s {int(timeout)}s {shlex.join(cmd)} 2>&1 | tee -a agent.log\n"
            "status=${PIPESTATUS[0]}\n"
            'echo "$status" > exit_code\n'
            'log "agent exited with status $status"\n'
            'exit "$status"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    @staticmethod
    def _start_session(session: str, workspace: Path, wrapper: Path) -> None:
        if not SESSION_RE.fullmatch(session):
            raise ValueError(f"Bad tmux session name: {session!r}")
        env_args = []
        for key in FORWARD_ENV:
            if key in os.environ:
                env_args += ["-e", f"{key}={os.environ[key]}"]
        env_args += ["-e", f"AGENT_LOG_DIR={workspace / 'log'}"]

        res = _tmux(
            "new-session", "-d",
            "-s", session,
            "-c", str(workspace),
            *env_args,
            "setsid", "bash", str(wrapper),
        )
        if res.returncode != 0:
            raise RuntimeError(
                f"tmux new-session failed: {res.stderr.strip()}"
            )

    def dispatch_agent_job(
        self,
        task: str,
        profile: str = "software-dev",
        max_turns: int = 40,
        timeout: int = 1800,
        session_name: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        if self.prompt_gen is None:
            raise RuntimeError("prompt_gen is required")

        workspace = Path(tempfile.mkdtemp(prefix=f"agent_run_{profile}_"))
        system_prompt_path = workspace / "system_prompt.md"
        task_path = workspace / "user_prompt.md"
        system_prompt_path.write_text(self.prompt_gen.generate_prompt(profile), encoding="utf-8")
        task_path.write_text(task, encoding="utf-8")

        cmd = [
            sys.executable, str(self.agent_dir / "run_agent.py"),
            "--backend", os.getenv("AGENT_BACKEND", self.backend),
            "--system-prompt", str(system_prompt_path),
            "--user-prompt", str(task_path),
            "--max-turns", str(max_turns),
        ]
        session_name = session_name or f"agent-{uuid.uuid4().hex[:8]}"
        wrapper = self._write_wrapper(workspace, cmd, timeout)
        self._start_session(session_name, workspace, wrapper)

        job_id = f"job_{uuid.uuid4().hex[:8]}"
        job = {
            "job_id": job_id,
            "session_name": session_name,
            "workspace": workspace,
            "log": workspace / "agent.log",
            "exit_file": workspace / "exit_code",
        }
        self.active_jobs[job_id] = job
        logger.info("Dispatched %s in session %s (%s)", job_id, session_name, workspace)
        return job_id, job

    # ---------- status ----------

    @staticmethod
    def is_running(job: Dict[str, Any]) -> bool:
        return _tmux("has-session", "-t", job["session_name"]).returncode == 0

    @staticmethod
    def exit_code(job: Dict[str, Any]) -> Optional[int]:
        try:
            return int(job["exit_file"].read_text().strip())
        except (OSError, ValueError):
            return None

    def is_working(self) -> bool:
        return any(self.is_running(j) for j in self.active_jobs.values())

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        job = self.active_jobs.get(job_id)
        if not job:
            return {"job_id": job_id, "status": "not_found"}

        running = self.is_running(job)
        code = self.exit_code(job)

        if running:
            status = "running"
        elif code is not None:
            status = "completed" if code == 0 else "failed"
        else:
            status = "finished_unknown"

        return {
            "job_id": job_id,
            "session_name": job["session_name"],
            "status": status,
            "exit_code": code,
            "workspace": str(job["workspace"]),
        }


    def get_job_output(self, job_id: str, tail_chars: int = 6000) -> str:
        job = self.active_jobs.get(job_id)
        if not job:
            return "Job not found."

        log = job["log"]
        if not log.exists():
            return "(no log yet)"

        return log.read_text(errors="replace")[-tail_chars:]

    # ---------- stopping ----------

    def stop_job(
        self,
        job_id: str,
        grace_seconds: float = 5.0,
    ) -> bool:
        job = self.active_jobs.get(job_id)
        if job is None:
            return False

        # The exit file is authoritative: don't kill an already-finished job.
        if self.exit_code(job) is not None:
            return True

        try:
            pgid = int(
                (job["workspace"] / "process_group_id")
                .read_text()
                .strip()
            )
        except (OSError, ValueError):
            logger.error("Cannot determine process group for %s", job_id)
            return False

        def group_exists() -> bool:
            try:
                os.killpg(pgid, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                return True

        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            logger.exception("Failed to signal process group for %s", job_id)
            return False

        deadline = time.monotonic() + grace_seconds
        while group_exists() and time.monotonic() < deadline:
            time.sleep(0.1)

        if group_exists():
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                logger.exception(
                    "Failed to kill process group for %s", job_id
                )
                return False

        # Wait briefly for the group to disappear after SIGKILL.
        deadline = time.monotonic() + 2.0
        while group_exists() and time.monotonic() < deadline:
            time.sleep(0.1)

        if group_exists():
            logger.error("Process group %s survived cancellation", pgid)
            return False

        # Only clean up tmux after the workload is gone.
        result = _tmux("kill-session", "-t", job["session_name"])
        if result.returncode != 0:
            logger.warning(
                "Workload stopped, but tmux cleanup failed for %s: %s",
                job_id,
                result.stderr.strip(),
            )

        # Deliberately retain active_jobs[job_id] for later inspection.
        return True

    def shutdown(self, stop_owned_jobs: bool = False) -> None:
        if stop_owned_jobs:
            for job_id in list(self.active_jobs):
                self.stop_job(job_id)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    sys.path.insert(0, os.environ.get("AGENT_DIR", "/agent"))
    import prompt_generator

    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--wait", type=int, default=60, help="seconds to follow the log in --test")
    args = parser.parse_args()

    dispatcher = AgentDispatcher(prompt_gen=prompt_generator.PromptGenerator())
    session_name=None
    if args.test:
        session_name = "agent-test"
    jid, info = dispatcher.dispatch_agent_job(args.task, session_name=session_name)
    print(f"Dispatched {jid}. Session: {info['session_name']}\nWorkspace: {info['workspace']}")

    if args.test:
        seen, deadline = 0, time.time() + args.wait
        if info["log"].exists():
            print(f"log exists at {info['log']}")
        while True:
            running = dispatcher.is_running(info)
            if info["log"].exists():
                text = info["log"].read_text(errors="replace")
                print(text[seen:], end="")
                seen = len(text)
            else:
                print(tmux_tools.tmux_capture(info["session_name"]))
            if not running or time.time() > deadline:
                break
            time.sleep(1)
        print(f"\n[{_get_timestamp}] Final: {'running' if running else 'exit ' + str(dispatcher.exit_code(info))}")
        # dispatcher.shutdown(stop_owned_jobs=True)