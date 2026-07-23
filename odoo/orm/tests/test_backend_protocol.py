"""Enforce the ``StorageBackend`` persistence contract.

``Environment.backend`` is ``None`` for PostgreSQL (the CRUD mixins run SQL
inline) or a :class:`StorageBackend` for the in-memory tier. The contract used
to be implicit: a new persistence op that added a backend method but forgot its
``if backend is not None`` dispatch site (or vice-versa) would silently run SQL
against the in-memory store -- exactly the row-lock gap that shipped. These
tests pin (a) that ``InMemoryBackend`` implements the whole Protocol, and (b)
that the Protocol methods and the dispatch sites are the same set, so either
kind of drift fails here. Pure introspection + source scan -- no database.

Dispatch sites live in the CRUD mixins (row-level ops) and in the field layer
(``fields/``: the Many2many relation-table ops in ``relational/many2many.py``),
so both directories are scanned.
"""

import pathlib
import re
import typing

from odoo.orm.runtime.backend import InMemoryBackend, StorageBackend

_ORM_DIR = pathlib.Path(__file__).resolve().parent.parent
_MIXINS_DIR = _ORM_DIR / "models" / "mixins"
_DISPATCH_DIRS = (_MIXINS_DIR, _ORM_DIR / "fields")

# Attribute (capability-flag) members: read as attributes, not dispatched as calls.
_ATTRIBUTE_MEMBERS = {"supports_parent_store", "supports_record_rules"}


def _protocol_methods() -> set[str]:
    return set(typing.get_protocol_members(StorageBackend)) - _ATTRIBUTE_MEMBERS


def test_in_memory_backend_implements_the_whole_protocol():
    missing = [
        m
        for m in typing.get_protocol_members(StorageBackend)
        if not hasattr(InMemoryBackend, m)
    ]
    assert not missing, f"InMemoryBackend does not implement: {missing}"


def test_every_protocol_method_has_a_dispatch_site():
    # collect ``backend.<name>(`` uses in the mixins and the field layer
    dispatched: set[str] = set()
    for directory in _DISPATCH_DIRS:
        for path in directory.rglob("*.py"):
            text = path.read_text()
            dispatched.update(re.findall(r"\bbackend\.([a-z_0-9]+)\(", text))
    methods = _protocol_methods()
    missing_dispatch = methods - dispatched
    unknown_dispatch = dispatched - methods - _ATTRIBUTE_MEMBERS
    assert not missing_dispatch, (
        f"StorageBackend methods with no dispatch site (they would run "
        f"SQL against the in-memory backend): {sorted(missing_dispatch)}"
    )
    assert not unknown_dispatch, (
        f"dispatch to backend methods not on the Protocol: "
        f"{sorted(unknown_dispatch)}"
    )


def test_supports_parent_store_is_consulted():
    # the one attribute member is read (not called) in create/write
    consulted = any(
        "backend.supports_parent_store" in path.read_text()
        for path in _MIXINS_DIR.rglob("*.py")
    )
    assert consulted, "supports_parent_store attribute is no longer consulted"


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
