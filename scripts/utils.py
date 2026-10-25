"""Small reusable helpers for the Kes 27 analysis scripts."""

import logging
from datetime import datetime
from pathlib import Path


def configure_logger(logger, log_dir, basename, *, file_level=logging.DEBUG,
                     stream_level=logging.INFO):
    """Attach timestamped file and terminal handlers to ``logger``."""
    log_dir = Path(log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    basename = Path(basename).name.removesuffix(".log")
    log_file = log_dir / f"{basename}_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(stream_level)

    for handler in (file_handler, stream_handler):
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return log_file


def require_file(path, label):
    """Return an existing file as an absolute Path."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def render_path(template, context):
    """Expand a ``str.format`` path template without resolving it."""
    return Path(str(template).format(**context)).expanduser()
