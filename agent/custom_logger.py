import logging
from datetime import datetime
from pathlib import Path
from logging import Logger
from typing import Any, Optional

class LoggerWrap:
    def __init__(self, name: str = "UnifiedAgent", level: str = "INFO", log_dir: Optional[Path] = None):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, level.upper()))
        self._logger.propagate=False

        # Prevent adding duplicate handlers if getLogger returns a cached instance
        if not self._logger.handlers:
            log_dir = log_dir or Path.cwd() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = log_dir / f"agent_{name}_{stamp}.log"
            fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(fmt)
            self._logger.addHandler(stream_handler)

            file_handler = logging.FileHandler(log_path, encoding="utf-8")

            file_handler.setFormatter(fmt)
            self._logger.addHandler(file_handler)

            self._logger.info(f"{name} logging initialized at {log_path}")

    # --- Magic method to make this wrapper act exactly like a standard logger ---
    def __getattr__(self, name: str):
        """Delegates standard logging calls (info, debug, error, etc.) to the underlying logger."""

        if getattr(self._logger, name):
            return getattr(self._logger, name)
        return getattr(self, name)

    @property
    def log_file(self) -> Optional[Path]:
        """Returns the path to the current active log file."""
        for handler in self._logger.handlers:
            if isinstance(handler, logging.FileHandler):
                return Path(handler.baseFilename)
        return None

    @property
    def log_dir(self) -> Optional[Path]:
        """Returns the directory of the current active log file."""
        if self.log_file:
            return self.log_file.parent
        return None

 # --- Custom Methods ---
    def set_log_dir(self, new_log_dir: Path) -> None:
        """Safely moves logging to a new directory by swapping the FileHandler."""
        new_log_dir = Path(new_log_dir)
        new_log_dir.mkdir(parents=True, exist_ok=True)

        # 1. Find and remove existing file handlers
        handlers_to_remove = [
            h for h in self._logger.handlers if isinstance(h, logging.FileHandler)
        ]

        for handler in handlers_to_remove:
            self._logger.removeHandler(handler)
            handler.close()  # CRITICAL: Release the file lock on the old log

        # 2. Create a new file handler in the new directory
        old_filename = handlers_to_remove[0].baseFilename.split('/')[-1] if handlers_to_remove else f"agent_{self._logger.name}.log"
        new_log_path = new_log_dir / old_filename

        new_file_handler = logging.FileHandler(new_log_path, encoding="utf-8")
        # Reuse the formatter from the stream handler
        new_file_handler.setFormatter(self._logger.handlers[0].formatter)

        self._logger.addHandler(new_file_handler)
        self._logger.info(f"Log directory changed. Now logging to {new_log_path}")



def setup_logging(name: str = "UnifiedAgent", level: str = "INFO", log_dir: Optional[Path] = None) -> LoggerWrap:
    """Factory function to create and return the wrapped logger."""
    return LoggerWrap(name=name, level=level, log_dir=log_dir)

def get_logger(name="UnifiedAgent", level="INFO", log_dir: Path | None = None) -> logging.Logger:
    if not log_dir:
        logger = logging.getLogger(name)
        logger.setLevel(level)
    return setup_logging(name, level, log_dir)
