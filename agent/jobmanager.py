from typing import Optional
from datetime import datetime
import time
import logging
import os
import threading
from pathlib import Path
from custom_logger import setup_logging

logger = setup_logging(__name__)

from llm_repl import LLMRepl
from agent.agent_dispatcher import OldAgentDispatcher, AgentDispatcher, TinyAgentDispatcher
from prompt_generator import PromptGenerator

AGENT_DIR = Path(__file__).parent


# Job manager facade retaining a simple API without changing LLMRepl internals.
class JobManager:
    def __init__(self, repl: LLMRepl):
        self.repl = repl
        if hasattr(self.repl, "_job_manager") and self.repl._job_manager and isinstance(self.repl._job_manager, JobManager):
            self.dispatcher = self.repl._job_manager.dispatcher
            self.prompt_gen = self.repl._job_manager.prompt_gen
            self._jobs = self.repl._job_manager._jobs
            self._jobs_lock = self.repl._job_manager._jobs_lock
            self.repl._job_manager = self
        else:
            setattr(self.repl, "_job_manager", self)
        self.dispatcher = AgentDispatcher()
        self.prompt_gen = repl.prompt_gen

        self._jobs = {}
        self._jobs_lock = threading.Lock()

    def dispatch(self, task: str, profile: str = "engineering", max_turns: int = 40, timeout: int = 1800, **kwargs) -> str:
        return self._dispatch_agent_job(task, profile=profile, max_turns=max_turns, timeout=timeout, **kwargs)

    def check(self, job_id: str) -> str:
        return self._check_job(job_id)

    def list(self) -> str:
        return self._list_jobs()




    def _job_watchdog(self, job_id: str, timeout: int) -> None:
        time.sleep(timeout)
        with self._jobs_lock:
            job = self._jobs.get(job_id)

            # if job and job["proc"].poll() is None: #NO PROC IN JOB
            if job:
                logger.warning(f"Job {job_id} timed out after {timeout}s. Killing.")
                self._kill_job_internal(job_id)

    def _kill_job_internal(self, job_id: str) -> None:
        if hasattr(self, 'dispatcher'):
            if isinstance(self.dispatcher, AgentDispatcher):
                self.dispatcher.stop_job(job_id)


    def _check_job(self, job_id:str) -> str:
        if not self.dispatcher:
            return f"Job {job_id} not found."
        try:
            log_text = self.dispatcher.get_job_output(job_id, tail_chars=2000)
            tail = log_text[-2000:]
        except Exception as e:
            tail = f"(log error: {e})"

        job_status = self.dispatcher.get_job_status(job_id)
        return (
            f"{job_id} {job_status['status']} (exit: {job_status['exit_code']})\n"
            f"Workspace: {job_status['workspace']}\n"
            f"--- log tail ---\n{tail}"
        )


    def _list_jobs(self) -> str:
        with self._jobs_lock:
            self._jobs = self.dispatcher.active_jobs or {}

            if not self._jobs:
                return "No jobs dispatched."

            lines = []
            for jid, j in self._jobs.items():
            # use dispatch there is no proc
                status = j["status"]
                if isinstance(j["start"], datetime):
                    j["start"] = j["start"].timestamp()
                elapsed = time.time() - j["start"]
                lines.append(f"{jid}: {status} ({elapsed:.0f}s, profile={j.get('profile', 'unknown')})")
            return "\n".join(lines)


    def _dispatch_agent_job(
            self,
            task: str,
            profile: str = "software-dev",
            backend: str = "ollama",
            model: Optional[str] = None,
            port: Optional[int] = None,
            max_turns: int = 40,
            timeout: int = 1800,
        ) -> str:
            if (
                not hasattr(self, "dispatcher")
                or not self.dispatcher
            ):
                self.dispatcher = OldAgentDispatcher(
                    agent_dir=str(AGENT_DIR),
                    prompt_gen=self.prompt_gen,
                )


            self.dispatcher.backend = backend
            self.dispatcher.model = (
                model
                or os.getenv(f"AGENT_MODEL_{backend.upper()}")
                or os.getenv("AGENT_MODEL")
            )
            self.dispatcher.port = port

            job_id, job = self.dispatcher.dispatch_agent_job(
                task,
                profile=profile,
                max_turns=max_turns,
                timeout=timeout,
            )
            with self._jobs_lock:
                self._jobs[job_id] = job
            logger.info(f"Job {job_id} dispatched.")

            # return job_id
            return (
                f"Dispatched {job_id} (profile={profile}). Running in background.\n"
                f"Workspace: {job['workspace']}\nLog: {job['log']}\n"
                f"Poll with check_job('{job_id}') or list_jobs()."
            )

            # dispatcher.active_jobs is a dict
