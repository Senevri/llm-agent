import logging
from datetime import datetime
from pathlib import Path

def setup_logging(name="UnifiedAgent", level="INFO", log_dir: Path | None = None) -> logging.Logger:
    log_dir = log_dir or Path.cwd() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"agent_{name}_{stamp}.log"

    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    fileh = logging.FileHandler(log_path, encoding="utf-8")
    fileh.setFormatter(fmt)

    logging.basicConfig(level=level, handlers=[stream, fileh], force=True)
    logger = logging.getLogger(name)
    logger.info(f"{name} Logging to {log_path}")
    return logger

def get_logger(name="UnifiedAgent", level="INFO", log_dir: Path | None = None) -> logging.Logger:
    if not log_dir:

        logger = logging.getLogger(name)
        logger.setLevel(level)
    return setup_logging(name, level, log_dir)
