import os
import re
import sys
import shlex
import logging
import tempfile
import subprocess
import time
from datetime import datetime, date
import uuid
import errno
import string
import signal
import threading
from pathlib import Path
from enum import StrEnum

from typing import Any, Dict, Optional, Tuple, Literal

logger = logging.getLogger("AgentDispatcher")

# Env vars forwarded into the tmux session (an existing tmux server won't inherit ours).
FORWARD_ENV = (
    "AGENT_BACKEND", "AGENT_MODEL", "AGENT_DIR", "AGENT_LOG_LEVEL",
    "OLLAMA_PORT", "OLLAMA_BASE_URL", "MISTRAL_API_KEY", "MISTRAL_BASE_URL",
    "PYTHONPATH",
)
SESSION_RE = re.compile(r"[A-Za-z0-9_-]+")  # tmux dislikes '.' and ':' in names

AGENT_DIR = os.environ.get("AGENT_DIR", "/agent")

if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import tools.tmux_tools as tmux_tools

def _tmux(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["tmux", *args], capture_output=True,
                              text=True, timeout=15)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(["tmux", *args], -1, "",
                                           f"tmux timed out: {e}")
def _get_timestamp() -> str:
    return date.fromtimestamp(time.time()).isoformat()


class Status(StrEnum):
    RUNNING="RUNNING"
    COMPLETED="COMPLETED"
    FAILED="FAILED"
    STOPPED="STOPPED"
    KILLED="KILLED"
    UNKNOWN="UNKNOWN"
    NOT_FOUND="NOT_FOUND"

    def __str__(self):
        return self.value


class AgentDispatcher:
    def __init__(self, agent_dir: Optional[str] = None, prompt_gen=None):
        self.agent_dir = Path(agent_dir or os.environ.get("AGENT_DIR", "/agent"))
        self.prompt_gen = prompt_gen
        self.backend = os.getenv("AGENT_BACKEND", "mistral")
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.model = None

    # ---------- launching ----------

    @staticmethod
    def _pgid_is_ours(pgid: int, workspace: Path) -> bool:
        if pgid <= 1:
            return False                # killpg(1) == kill(-1) == "everyone"
        if pgid == os.getpgrp():
            return False                # never signal ourselves
        try:
            cmdline = Path(f"/proc/{pgid}/cmdline").read_bytes()
        except OSError:
            return False
        return str(workspace).encode() in cmdline

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
    def  _start_session(session: str, workspace: Path, wrapper: Path) -> None:
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
            "setsid", "-f", "-w", "bash", str(wrapper),
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
        if self.model is not None:
            cmd += ["--model", self.model]

        session_name = session_name or f"agent-{uuid.uuid4().hex[:8]}"
        wrapper = self._write_wrapper(workspace, cmd, timeout)
        self._start_session(session_name, workspace, wrapper)

        job_id = f"job_{uuid.uuid4().hex[:8]}"
        job = {
            "job_id": job_id,
            "start": datetime.now(),
            "timeout": timeout,
            "status": Status.RUNNING,
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
        return _tmux("has-session", "-t", f"={job['session_name']}").returncode == 0

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
            return {"job_id": job_id, "status": Status.NOT_FOUND}

        stopped = job.get("stopped")
        running = self.is_running(job)
        code = self.exit_code(job)

        # TODO: figure out correct logic
        if running:
            status = Status.RUNNING
        elif stopped:
            status = Status.STOPPED
        elif code is not None:
            status = Status.COMPLETED if code == 0 else Status.FAILED
        else:
            status = Status.UNKNOWN

        return {
            "job_id": job_id,
            "session_name": job["session_name"],
            "start": job["start"],
            "timeout": job["timeout"],
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
    def _wait_gone(self, pgid: int, workspace: Path, seconds: float) -> bool:
        """Return True once the pgid is gone *or* no longer ours."""
        deadline = time.monotonic() + seconds
        while True:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                pass                       # something owns it — check identity
            # Owned and still ours → still our workload.
            if not self._pgid_is_ours(pgid, workspace):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def _resolve_pgid(self, job: Dict[str, Any]) -> Optional[int]:
        """pgid written by the wrapper, falling back to the tmux pane pid."""
        try:
            pgid = int((job["workspace"] / "process_group_id").read_text().strip())
            if pgid > 1 and pgid != os.getpgrp():
                return pgid
            return None
        except (OSError, ValueError):
            pass

        res = _tmux("display-message", "-p",
                    "-t", f"={job['session_name']}", "#{pane_pid}")
        if res.returncode != 0:
            return None
        try:
            pgid = int(res.stdout.strip())
        except ValueError:
            return None
        if pgid <= 1 or pgid == os.getpgrp():
            return None
        # `setsid` execs in place when not a group leader, so pane_pid == pgid.
        return pgid

    def stop_job(self, job_id, grace_seconds=5.0):
        job = self.active_jobs.get(job_id)
        if job is None:
            return False
        if job.get("stopped") or self.exit_code(job) is not None:
            job["stopped"] = True
            return True

        with job.setdefault("_stop_lock", threading.Lock()):
            if job.get("stopped"):
                return True
            pgid = self._resolve_pgid(job)      # file, else tmux pane_pid
            if pgid is None or not self._pgid_is_ours(pgid, job["workspace"]):
                _tmux("kill-session", "-t", f"={job['session_name']}")
                job["stopped"] = not self.is_running(job)
                return job["stopped"]

            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError:
                logger.exception("SIGTERM failed for %s", job_id)
                return False

            if self._wait_gone(pgid, job["workspace"], grace_seconds):
                return self._finish_stop(job, pgid, "SIGTERM")

            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if self._wait_gone(pgid, job["workspace"], 2.0):
                return self._finish_stop(job, pgid, "SIGKILL")

            logger.error("pgid %s survived SIGKILL or was reused", pgid)
            _tmux("kill-session", "-t", f"={job['session_name']}")
            return False

    def _finish_stop(self, job, pgid, how):
        job["stopped"] = True
        job["stop_signal"] = how
        _tmux("kill-session", "-t", f"={job['session_name']}")
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
        print(f"\n[{_get_timestamp()}] Final: {'running' if running else 'exit ' + str(dispatcher.exit_code(info))}")
        # dispatcher.shutdown(stop_owned_jobs=True)