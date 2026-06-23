"""Canonical public import path for the per-database :class:`Registry`.

The registry is *implemented* in :mod:`odoo.orm.runtime.registry` -- a registry
is fundamentally an ORM concept, so that is where the class lives.  This module
is the **stable, canonical import location** used by everything outside
:mod:`odoo.orm`::

    from odoo.modules.registry import Registry

Application code, addons, CLI commands, HTTP handling, the module loader and
tests import ``Registry`` (and the registry-cache globals) from here rather than
reaching into ``odoo.orm.runtime``.  Only ``odoo.orm`` internals import the
class directly from the implementation module.  Keeping a single public path
avoids the "which import is canonical?" ambiguity.
"""

from odoo.orm.runtime import (
    _CACHES_BY_KEY,
    _REGISTRY_CACHES,
    DummyRLock,
    Registry,
)

__all__ = [
    "_CACHES_BY_KEY",
    "_REGISTRY_CACHES",
    "DummyRLock",
    "Registry",
]
