import threading
import queue
import time
from typing import List, Dict
from user_profile_manager import ContextSnapshot
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

#from llm_repl import LLMRepl

# --- Profiling worker --------------------------------------------------------------
class ProfileWorker(threading.Thread):
    """Background worker that consumes profiling tasks and updates the user profile."""

    def __init__(self, repl, q: queue.Queue, batch_size: int = 3, time_threshold: float = 0.5):
        super().__init__(daemon=True, name="ProfileWorker")
        self.repl = repl
        self.queue = q
        self.batch_size = batch_size
        self.time_threshold = time_threshold
        self._stop_event = threading.Event()
        self.batch: List[ContextSnapshot] = []
        self.api=None
        self.console=None
        self.dispatcher = None

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.queue.put(None)
        except Exception:
            pass
        self.repl._consolidate_profile()


    def run(self) -> None:
        logger.info("ProfileWorker thread started.")
        while not self._stop_event.is_set():
            try:
                snapshot = self.queue.get(timeout=1.0)
                if snapshot is None:
                    self._process_batch()
                    break
                self.batch.append(snapshot)
                if len(self.batch) >= self.batch_size:
                    self._process_batch()
                self.queue.task_done()
            except queue.Empty:
                if self.batch and (time.time() - self.batch[-1].timestamp >= self.time_threshold):
                    self._process_batch()
            except Exception as e:
                logger.exception(f"ProfileWorker error: {e}")
        logger.info("ProfileWorker thread shutting down.")

    # def _process_batch(self) -> None:
    #     if not self.batch:
    #         return
    #     latest = self.batch[-1]
    #     prompt = self.repl.prompt_gen.generate_prompt("profiler")
    #     self.repl._apply_profile_update(latest.user_input, latest.assistant_response, prompt=prompt)
    #     self.batch = []

    def _process_batch(self) -> None:
        if not self.batch:
            return

        latest = self.batch[-1]
        prompt = ""

        # Safely attempt to load the prompt template
        if hasattr(self.repl, 'prompt_gen') and self.repl.prompt_gen:
            try:
                prompt = self.repl.prompt_gen.generate_prompt("profiler") or ""
            except Exception as e:
                logger.warning(f"Failed to generate profiler prompt: {e}")

        # Hardcoded fallback that perfectly matches your profiler.md rules
        if not prompt or "{profile_json}" not in prompt or "{user_input}" not in prompt:
            logger.warning("Using fallback profiler prompt (template missing or malformed)")
            prompt = (
                "You are a profiling agent. Maintain a structured JSON profile of the user using only the evidence in the current user message.\n"
                "Current profile:\n{profile_json}\n"
                "User message this turn (the ONLY new evidence you may use):\n<<<\n{user_input}\n>>>\n"
                "Rules:\n"
                "- Record independently meaningful facts about the user.\n"
                "- Do not infer anything from assistant messages.\n"
                "- Preserve existing facts unless clearly updated or contradicted.\n"
                "- Return the complete updated profile as valid JSON.\n"
                "- Do not include markdown fences, explanations, or commentary.\n"
                "- If there are no profile updates, return the existing profile unchanged."
            )

        # Ensure all placeholders are injected
        prompt = prompt.replace("{profile_json}", json.dumps(self.repl.profile_manager.profile_data, indent=2)) \
                       .replace("{user_input}", latest.user_input)

        logger.info(f"Sending profile update request for input: {latest.user_input[:50]}...")

        self.repl._apply_profile_update(
            latest.user_input,
            latest.assistant_response,
            prompt=prompt
        )
        self.batch = []