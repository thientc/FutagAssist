"""Logging for the build stage: LLM Q&A, build result, and other useful info."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

LOGGER_NAME = "futagassist.build"


def get_logger() -> logging.Logger:
    """Return the build-stage logger."""
    return logging.getLogger(LOGGER_NAME)


@contextmanager
def build_log_context(
    log_file: Path,
    verbose: bool = False,
) -> Generator[logging.Logger, None, None]:
    """
    Attach a file handler to the build logger for the duration of the context.
    Log file is UTF-8; format: timestamp [LEVEL] message.
    """
    logger = get_logger()
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    try:
        yield logger
    finally:
        logger.removeHandler(handler)
