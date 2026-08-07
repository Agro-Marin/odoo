import logging
from typing import Any

__all__ = ["ASSET_ROOT", "get_asset_logger", "log_event"]

ASSET_ROOT = "odoo.assets"


def get_asset_logger(category: str) -> logging.Logger:
    if not category:
        return logging.getLogger(ASSET_ROOT)
    return logging.getLogger(f"{ASSET_ROOT}.{category}")


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    if not logger.isEnabledFor(level):
        return
    parts = [f"event={event}"]
    parts.extend(f"{k}={v}" for k, v in fields.items())
    logger.log(level, "%s", " ".join(parts))
