"""Centralized logging setup.

Usage:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Workflow registered: %s", workflow_id)
"""

import logging
import sys
from typing import Optional

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
_LOG_FILE = "app.log"

# Track which loggers have already been configured to avoid duplicate handlers
_configured: set[str] = set()


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """Return a configured logger that writes to console and app.log.

    Args:
        name: Logger name (use __name__ in calling modules).
        level: Optional override for the log level (default: DEBUG).

    Returns:
        A configured Logger instance.
    """
    logger = logging.getLogger(name)

    if name in _configured:
        return logger

    log_level = level if level is not None else logging.DEBUG
    logger.setLevel(log_level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # File handler
    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False

    _configured.add(name)
    return logger
