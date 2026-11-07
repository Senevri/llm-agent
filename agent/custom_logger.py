import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


class LoggerWrap:
    def __init__(self, name: str = "UnifiedAgent", level: str = "INFO", log_dir: Optional[Path] = None):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, level.upper()))
        self._logger.propagate = False

        # Check specifically for FileHandler to prevent duplicate file writes on re-init
        has_file_handler = any(isinstance(h, logging.FileHandler) for h in self._logger.handlers)

        if not has_file_handler:
            log_dir = log_dir or Path.cwd() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = log_dir / f"agent_{name}_{stamp}.log"
            fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')

            # Only add stream handler if no handlers exist at all
            if not self._logger.handlers:
                stream_handler = logging.StreamHandler()
                stream_handler.setFormatter(fmt)
                self._logger.addHandler(stream_handler)

            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(fmt)
            self._logger.addHandler(file_handler)

            self._logger.info(f"{name} logging initialized at {log_path}")

    def __getattr__(self, name: str):
        """Cleanly delegates standard logging calls to the underlying logger."""
        return getattr(self._logger, name)

    @property
    def log_file(self) -> Optional[Path]:
        for handler in self._logger.handlers:
            if isinstance(handler, logging.FileHandler):
                return Path(handler.baseFilename)
        return None

    @property
    def log_dir(self) -> Optional[Path]:
        if self.log_file:
            return self.log_file.parent
        return None

    def set_log_dir(self, new_log_dir: Path) -> None:
        new_log_dir = Path(new_log_dir)
        new_log_dir.mkdir(parents=True, exist_ok=True)

        handlers_to_remove = [h for h in self._logger.handlers if isinstance(h, logging.FileHandler)]
        for handler in handlers_to_remove:
            self._logger.removeHandler(handler)
            handler.close()

        old_filename = handlers_to_remove[0].baseFilename.split('/')[-1] if handlers_to_remove else f"agent_{self._logger.name}.log"
        new_log_path = new_log_dir / old_filename

        new_file_handler = logging.FileHandler(new_log_path, encoding="utf-8")
        fmt = self._logger.handlers[0].formatter if self._logger.handlers else logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        new_file_handler.setFormatter(fmt)

        self._logger.addHandler(new_file_handler)
        self._logger.info(f"Log directory changed. Now logging to {new_log_path}")


class LoggerFactory:
    loggers = {}

    def __init__ (self):
        pass

    def get_logger(self, name: str = "UnifiedAgent", level: str = "INFO", log_dir: Optional[Path] = None) -> LoggerWrap:
        if name not in self.loggers:
            self.loggers[name] = LoggerWrap(name=name, level=level, log_dir=log_dir)
        return self.loggers[name]

factory = LoggerFactory()

def setup_logging(name: str = "UnifiedAgent", level: str = "INFO", log_dir: Optional[Path] = None) -> LoggerWrap:
    return factory.get_logger(name=name, level=level, log_dir=log_dir)