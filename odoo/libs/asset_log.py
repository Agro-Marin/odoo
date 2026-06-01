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

Event format — when ``log_event`` is used, the formatted record looks
like (logger name comes from Python's log handler, message is the body)::

    odoo.assets.esbuild INFO event=invoke bundle=web.assets_web modules=603

The ``event=<name> k1=v1 k2=v2`` body is ``grep``/``awk`` friendly and
trivially parseable into JSON lines by downstream log aggregators.
"""

import logging
from typing import Any

__all__ = ["ASSET_ROOT", "get_asset_logger", "log_event"]

ASSET_ROOT = "odoo.assets"


def get_asset_logger(category: str) -> logging.Logger:
    """Return the logger for the given asset category.

    All asset loggers are children of ``odoo.assets`` so a single handler
    can capture the whole pipeline.
    """
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

    Keeps format strings simple (no ``%s`` juggling when fields vary) and
    produces output that survives raw ``grep`` queries as well as JSON
    conversion via ``awk '{for(i=2;i<=NF;i++){split($i,a,"=");print a[1]": "a[2]}}'``
    or similar shell one-liners.
    """
    if not logger.isEnabledFor(level):
        return
    parts = [f"event={event}"]
    parts.extend(f"{k}={v}" for k, v in fields.items())
    logger.log(level, "%s", " ".join(parts))
