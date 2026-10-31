"""Extracted looptask (LoopTask) from llm_repl.py for further development."""

import logging
import os
import sys
from datetime import timedelta, datetime
from queue import Queue
import threading
import uuid
from typing import Dict, Any, List, Callable, NamedTuple, Optional, Union, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, field
from agent_dispatcher import AgentDispatcher, Status as AgentStatus

# --- Stubs for rich (mirrors original) ---
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    console = Console(
        file=sys.__stdout__,
        force_terminal=True,
        color_system="auto",
    )
except Exception:
    class Console:  # type: ignore
        def print(self, msg, *args, **kwargs):
            print(msg)
        def rule(self, title):
            print(f"--- {title} ---")
    class Markdown:  # type: ignore
        def __init__(self, text):
            self.text = text
    class Panel:  # type: ignore
        def __init__(self, content, title=None):
            self.content = content
            self.title = title
    class Table:  # type: ignore
        def __init__(self, title=None):
            self.title = title
        def add_column(self, *a, **k):
            pass
        def add_row(self, *a, **k):
            pass
    console = Console()

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    prompt_session = PromptSession(history=FileHistory(str("/workspace")))
except Exception:
    prompt_session = None

if os.getenv("DEBUG"):
    # --- Stubs for LLMRepl, AgentDispatcher, AgentStatus ---
    class AgentStatus:  # type: ignore
        COMPLETED = "completed"
        FAILED = "failed"

    class LLMRepl:  # type: ignore
        pass

    class AgentDispatcher:
        def get_job_output(self, jid):
            return None

        def dispatch_agent_job(self, task, session_name=None):
            return (None, {})

        def shutdown(self, stop_owned_jobs=False):
            pass


# --- LoopTask ---
class LoopTask:
    import threading
    def __init__(self, repl, task):
        self.repl: LLMRepl = repl
        self.started_at = None
        self.ends_at = None
        self.task = task
        self.commands = queue.Queue()
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.agent = None
        self.backend_settings = {
            "backend": self.repl.backend,
            "port": self.repl.api.port,
            "model": self.repl.model,
        }
        self.thread = None


    def start(self):
        self.started_at = datetime.now()
        self.repl.loop_task = self
        self.thread = threading.Thread(
            target=self.run,
            kwargs={"stop_event": self.stop_event},
            daemon=True)
        self.thread.start()
        return self

    def get_output(self):
        if not self.agent:
            return
        dispatcher, jid, info = self.agent
        return dispatcher.get_job_output(jid)

    def _run_loop(self):
        while not self.stop_event.is_set():
            if self.pause_event.wait(timeout=0.5):
                continue

            if self.agent:
                dispatcher, jid, info = self.agent
                if dispatcher.get_job_status(jid) in [AgentStatus.COMPLETED, AgentStatus.FAILED]:
                    with self.repl._state_lock:
                        output = dispatcher.get_job_output(jid)
                        console.print(Markdown(output))
                        #self.repl.messages += [{"role": "assistant", "content": output}]

                    if self.check_timeout():

                        dispatcher.shutdown(stop_owned_jobs=True)
                        break
                    else:
                        jid, info = dispatcher.dispatch_agent_job(self.task, session_name=info["session_name"])
                        with self.repl._jobs_lock:
                            self.repl._jobs[jid] = info
                        self.agent = (dispatcher, jid, info)
            else:
                dispatcher = AgentDispatcher(prompt_gen=self.repl.prompt_gen)
                dispatcher.backend="mistral"
                # dispatcher.backend = self.backend_settings.get("backend", "mistral")
                # dispatcher.port = self.backend_settings.get("port")
                # dispatcher.model = self.backend_settings.get("model")

                session_name=f"agent-loop-{uuid.uuid4().hex[:8]}"
                jid, info = dispatcher.dispatch_agent_job(self.task, session_name=session_name)
                self.agent = (dispatcher, jid, info)

            if self.ends_at and datetime.now() > self.ends_at:
                output = dispatcher.get_job_output(jid)
                console.print(output)
                self.stop()

    def run(self, *args, **kwargs):
        logger.info(f"Starting LoopTask... {args} {kwargs}")
        try:
            self._run_loop()
        except Exception as e:
            logger.error(f"LoopTask error: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        if self.agent:
            dispatcher, jid, info = self.agent
            dispatcher.shutdown(stop_owned_jobs=True)
        self.repl.loop_task = None
        self.agent = None
        self.thread = None


    def check_timeout(self):
        if self.ends_at and datetime.now() > self.ends_at:
            self.stop()
            return True
        return False

    def stop(self):
        self.stop_event.set()
        self.started_at=None

    def set_end(self, end):
        self.ends_at = end

    def pause(self):
        self.pause_event.set()

    def resume(self):
        self.pause_event.clear()


def loop (repl, *args, **kwargs):

    if "start" in args:
        task_prompt = kwargs.get("task", None)
        if not task_prompt:
            console.print("[red]No task prompt provided[/red]")
            return

        if repl.loop_task and repl.loop_task.is_running():
            console.print("[red]Loop task already running[/red]")
            return


        loop_task = LoopTask(repl, task_prompt)
        loop_task.started_at = datetime.now()
        # add parsing of timedelta
        hours = int(kwargs.get("hours", 0))
        minutes = int(kwargs.get("minutes", 0))
        seconds = int(kwargs.get("seconds", 0))
        # form a time delta

        # add the delta to the current time
        delta = timedelta(hours=hours, minutes=minutes, seconds=seconds)
        loop_task.set_end(loop_task.started_at + delta)
        loop_task.start()
        return loop_task

    elif "stop" in args:
        if repl.loop_task:
            # get output from any agents
            console.print(repl.loop_task.get_output())
            repl.loop_task.stop()
            repl.loop_task.cleanup()
        else:
            console.print("[red]No loop task running[/red]")

    elif "check" in args:
        if repl.loop_task:
            console.print(repl.loop_task.get_output())
        else:
            console.print("[red]No loop task running[/red]")
    return None
