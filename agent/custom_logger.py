import logging
from datetime import datetime
from pathlib import Path

def setup_logging(level, log_dir: Path | None = None) -> logging.Logger:
    log_dir = log_dir or Path.cwd()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"agent_{stamp}.log"

    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    fileh = logging.FileHandler(log_path, encoding="utf-8")
    fileh.setFormatter(fmt)

    logging.basicConfig(level=level, handlers=[stream, fileh], force=True)
    logger = logging.getLogger("UnifiedAgent")
    logger.info(f"Logging to {log_path}")
    return logger
