"""Small reusable helpers for the Kes 27 analysis scripts."""

import faulthandler
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

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
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

    faulthandler.enable(file=file_handler.stream)
    return log_file


def run_with_error_logging(main, logger, basename):
    """Log a workflow failure with its traceback and return a nonzero status."""
    try:
        main()
    except (Exception, KeyboardInterrupt):
        if not logger.handlers:
            try:
                log_file = configure_logger(logger, "../logs", basename)
                logger.info("Log file: %s", log_file)
            except OSError as error:
                logger.error("Could not open the fallback log: %s", error)
        logger.exception("Workflow stopped")
        return 1
    return 0


def require_file(path, label):
    """Return an existing file as an absolute Path."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def render_path(template, context):
    """Expand a ``str.format`` path template without resolving it."""
    return Path(str(template).format(**context)).expanduser()
