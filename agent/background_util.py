import threading
import queue
import traceback
import time
from typing import Callable, Any, Optional, List

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

        self._thread = threading.Thread(target=self._run_worker, daemon=True, name=f"BgProc-{self.func.__name__}")
        self._thread.start()

    def _run_worker(self) -> None:
        try:
            # Inject a thread-safe callback so the function can push intermediate status
            def push_output(msg: str) -> None:
                if self._is_running:
                    self.output_queue.put(f"[{time.strftime('%H:%M:%S')}] {msg}")

            self.kwargs['push_output'] = push_output
            self.result = self.func(*self.args, **self.kwargs)
        except Exception as e:
            self.error = e
            self.output_queue.put(f"❌ ERROR: {e}\n{traceback.format_exc()}")
        finally:
            self._is_running = False
            self.output_queue.put(None)  # Sentinel value indicating completion

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