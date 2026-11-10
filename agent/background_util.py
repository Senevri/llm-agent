import threading
import queue
import traceback
import time
from typing import Callable, Any, Optional, List
import inspect
import logging
from custom_logger import setup_logging

logger = setup_logging(__name__)

try:
    from rich.console import Console
    import logging
    from rich.logging import RichHandler

    FORMAT = "%(message)s"
    logging.basicConfig(
        level="NOTSET", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
    )
except ImportError:
    class console:
        def print(self, msg, *args, **kwargs):
            print(msg, *args, **kwargs)

        def rule(self, title):
            print(f"--- {title} ---")

class BackgroundProcess:
    def __init__(self, func: Callable, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.output_queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self.result: Any = None
        self.error: Optional[Exception] = None

    def start(self) -> None:
        if self._is_running:
            return

        self._is_running = True
        self.result = None
        self.error = None

        # Clear any stale messages from previous runs
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except queue.Empty:
                break

        self._thread = threading.Thread(
            target=self._run_worker, daemon=True, name=f"BgProc-{self.func.__name__}")
        self._thread.start()

    def stop(self) -> Any:
        self._is_running = False
        if self._thread:
            self._thread.join()
            self._thread = None
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except queue.Empty:
                break
        self.output_queue.put(None)
        return self.result

    def _accepts_push_output(self) -> bool:
        try:
            sig = inspect.signature(self.func)
        except (TypeError, ValueError):
            return False

        for p in sig.parameters.values():
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                return True

        p = sig.parameters.get("push_output")
        return (
            p is not None
            and p.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        )

    def _run_worker(self) -> None:
        try:
            def push_output(msg: str) -> None:
                if self._is_running:
                    self.output_queue.put(f"[{time.strftime('%H:%M:%S')}] {msg}")

            kwargs = self.kwargs.copy()

            if self._accepts_push_output():
                kwargs["push_output"] = push_output

            self.result = self.func(*self.args, **kwargs)

        except Exception as e:
            self.error = e
            self.output_queue.put(f"❌ ERROR: {e}\n{traceback.format_exc()}")

        finally:
            self._is_running = False
            self.output_queue.put(None)

    @property
    def is_running(self) -> bool:
        # Check if thread is alive and flag is set
        return self._is_running and self._thread is not None and self._thread.is_alive()

    def get_pending_output(self) -> List[str]:
        """Non-blocking drain of all available intermediate outputs."""
        outputs = []
        while True:
            try:
                msg = self.output_queue.get_nowait()
                if msg is None:  # EOF sentinel
                    break
                outputs.append(msg)
            except queue.Empty:
                break
        return outputs

    def wait(self, timeout: Optional[float] = None) -> Any:
        """Blocking wait for completion. Returns result or raises error."""
        if self._thread:
            self._thread.join(timeout=timeout)
        if self.error:
            raise self.error
        return self.result


def run_in_background(func: Callable) -> Callable:
    """
    Decorator that transforms a blocking function into one that
    immediately returns a BackgroundProcess instance.
    """
    def wrapper(*args, **kwargs):
        proc = BackgroundProcess(func, *args, **kwargs)
        proc.start()
        return proc


    return wrapper