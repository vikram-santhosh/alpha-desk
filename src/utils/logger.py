"""Structured logging for AlphaDesk agents."""

import logging
import sys
from pathlib import Path


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Create a structured logger for the given module.

    Args:
        name: Logger name, typically __name__ of the calling module.
        level: Logging level, defaults to INFO.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)-25s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File handler — logs to data/alphadesk.log
    log_dir = Path("data")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "alphadesk.log")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
