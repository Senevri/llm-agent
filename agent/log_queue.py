import logging
import queue
import sys
import threading

DEFAULT_FMT = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

# --- Logging setup (queue-decoupled) ---------------------------------------------
class LogQueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put(record)
        except Exception:
            self.handleError(record)


class LogQueueListener(threading.Thread):
    def __init__(self, log_queue: queue.Queue, formatter=None):
        super().__init__(daemon=True, name="LogQueueListener")
        self.log_queue = log_queue


        self.formatter = formatter or DEFAULT_FMT
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()
        try:
            self.log_queue.put(None)
        except Exception:
            pass

    def run(self):
        while not self._stop_event.is_set():
            try:
                record = self.log_queue.get(timeout=1.0)
                if record is None:
                    break
                try:
                    msg = self.formatter.format(record) if self.formatter else record.getMessage()
                except Exception as e:
                    msg = f"<format error: {e}> {record.getMessage()}"
                sys.stderr.write(msg if msg.endswith("\n") else msg + "\n")
                sys.stderr.flush()
                self.log_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                sys.stderr.write(f"LogQueueListener error: {e}\n")