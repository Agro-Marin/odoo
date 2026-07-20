r"""Structured logging for the asset bundler pipeline.

Mirrors the client-side ``@web/core/utils/asset_log`` helper so that the
whole Python→esbuild→browser chain can be traced through one logger
hierarchy.  All asset events go to loggers rooted at ``odoo.assets``, so
admins can enable verbose asset tracing with a single switch::

    odoo-bin --log-handler=odoo.assets:DEBUG

Per-subsystem granularity is available via children loggers::

    odoo-bin --log-handler=odoo.assets.esbuild:INFO \\
             --log-handler=odoo.assets.bridge:DEBUG

Categories (kept in sync with the JS side):

    boot       Boot-time events (shim load, odoo.loader creation)
    esm        Import-map & bundle-node generation in ir_qweb
    bundle     AssetsBundle lifecycle (init, has_js/has_css, link-gen)
    bridge     Native-to-legacy data-URI bridge construction
    esbuild    esbuild subprocess invocations
    loader     module_loader.js shim compilation
    attach     ir.attachment writes/reuse for bundle output
    fallback   Degraded path activations (prod→debug, try-lock miss)
    lock       Advisory-lock acquire/release for concurrent builds

A ``log_event`` record formats as (the body is ``grep``-friendly)::

    odoo.assets.esbuild INFO event=invoke bundle=web.assets_web modules=603
"""

import logging
from typing import Any

__all__ = ["ASSET_ROOT", "get_asset_logger", "log_event"]

ASSET_ROOT = "odoo.assets"


def get_asset_logger(category: str) -> logging.Logger:
    """Return the ``odoo.assets.<category>`` logger."""
    if not category:
        return logging.getLogger(ASSET_ROOT)
    return logging.getLogger(f"{ASSET_ROOT}.{category}")


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    """Emit a structured ``event=<name> k1=v1 k2=v2`` record.

    The flat ``key=value`` body stays readable across varying fields and is
    easy to ``grep`` or parse into JSON.
    """
    if not logger.isEnabledFor(level):
        return
    parts = [f"event={event}"]
    parts.extend(f"{k}={v}" for k, v in fields.items())
    logger.log(level, "%s", " ".join(parts))
