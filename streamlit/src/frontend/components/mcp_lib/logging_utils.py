from __future__ import annotations

import logging
from typing import Final

_LOGGER_NAME: Final[str] = "arc.metamask"


def get_metamask_logger() -> logging.Logger:
    """Return a shared logger for MetaMask pop-up tracking."""

    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
