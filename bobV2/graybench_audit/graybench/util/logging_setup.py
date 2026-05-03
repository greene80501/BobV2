"""Structured logging setup for GrayBench."""

import logging
import sys


def setup_logging(level: str = "INFO", fmt: str = None):
    """Configure logging for the application."""
    log_fmt = fmt or "%(asctime)s %(name)-30s %(levelname)-5s %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_fmt,
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
