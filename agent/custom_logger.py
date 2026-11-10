import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Union
from logging import Handler

LevelLike = Union[int, str]


def _to_level(level: LevelLike) -> int:
    if isinstance(level, int):
        return level
    value = logging.getLevelName(level.upper())   # "WARN" -> 30, "Warn" -> 30
    if not isinstance(value, int):
        raise ValueError(f"Unknown log level: {level!r}")
    return value


def _is_file(h: logging.Handler) -> bool:
    return isinstance(h, logging.FileHandler)


def _is_console(h: logging.Handler) -> bool:
    # FileHandler subclasses StreamHandler, so isinstance(h, StreamHandler)
    # matches files too. Exclude them explicitly.
    return isinstance(h, logging.StreamHandler) and not _is_file(h)


class LoggerWrap:
    FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'

    def __init__(self, name: str = "UnifiedAgent", level: LevelLike = "INFO",
                 log_dir: Optional[Path] = None, file_level: LevelLike = "DEBUG"):
        self._logger = logging.getLogger(name)
        self._logger.propagate = False
        console_level = _to_level(level)
        file_lvl = _to_level(file_level)
        # Logger passes the union; handlers do the real filtering.
        self._logger.setLevel(min(console_level, file_lvl))

        fmt = logging.Formatter(self.FORMAT)

        if not any(_is_console(h) for h in self._logger.handlers):
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            sh.setLevel(console_level)
            self._logger.addHandler(sh)

        if not any(_is_file(h) for h in self._logger.handlers):
            log_dir = Path(log_dir) if log_dir else Path.cwd() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = log_dir / f"{name}_{stamp}.log"
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(fmt)
            fh.setLevel(file_lvl)
            self._logger.addHandler(fh)
            self._logger.info("%s logging initialized at %s", name, log_path)

    def __getattr__(self, name: str):
        return getattr(self._logger, name)

    def set_console_level(self, level: LevelLike) -> None:
        """What the REPL's loglevel command should call. Never touches the file."""
        lvl = _to_level(level)
        for h in self._logger.handlers:
            if _is_console(h):
                h.setLevel(lvl)
        file_lvls = [h.level for h in self._logger.handlers if _is_file(h)]
        self._logger.setLevel(min([lvl, *file_lvls]))

    @property
    def log_file(self) -> Optional[Path]:
        for h in self._logger.handlers:
            if _is_file(h):
                return Path(h.baseFilename)
        return None

    @property
    def log_dir(self) -> Optional[Path]:
        return self.log_file.parent if self.log_file else None

    def set_log_dir(self, new_log_dir: Path) -> None:
        new_log_dir = Path(new_log_dir)
        new_log_dir.mkdir(parents=True, exist_ok=True)

        old = [h for h in self._logger.handlers if _is_file(h)]
        for h in old:
            self._logger.removeHandler(h)
            h.close()

        filename = Path(old[0].baseFilename).name if old else \
            f"{self._logger.name}_{datetime.now():%Y%m%d_%H%M%S}.log"
        fh = logging.FileHandler(new_log_dir / filename, encoding="utf-8")
        fh.setFormatter(old[0].formatter if old else logging.Formatter(self.FORMAT))
        fh.setLevel(old[0].level if old else logging.DEBUG)   # keep the file's own level
        self._logger.addHandler(fh)
        self._logger.info("Log directory changed. Now logging to %s", fh.baseFilename)

class LoggerFactory:
    loggers = {}

    def __init__ (self):
        pass

    def get_logger(self, name: str = "UnifiedAgent", level: str = "INFO", log_dir: Optional[Path] = None) -> LoggerWrap:
        if name not in self.loggers:
            self.loggers[name] = LoggerWrap(name=name, level=level, log_dir=log_dir)
        return self.loggers[name]

factory = LoggerFactory()

def setup_logging(name: str = "UnifiedAgent", prefix: str = "", level: str = "INFO", log_dir: Optional[Path] = None) -> LoggerWrap:
    return factory.get_logger(name=f"{prefix}{name}", level=level, log_dir=log_dir)

if __name__ == "__main__":
    log = setup_logging("test", level="WARNING", log_dir=Path.cwd() / "logs")
    log.debug("test")
    log.info("test")
    log.warning("test")
    log.error("test")
    log.critical("test")
    # Test: do messages go to files?