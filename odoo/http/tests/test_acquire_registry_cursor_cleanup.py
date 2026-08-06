"""``_acquire_registry_cursor`` must never leak its read-only cursor.

It opens a read-only cursor, then calls ``registry.check_signaling(cr)``.  Its
``except`` clause only names ``PoolError`` / ``OperationalError`` /
``ProgrammingError`` and closes ``cr`` in that clause's ``finally``.  Anything
else — an ``InternalError`` / ``DataError`` from ``check_signaling``, a bug in a
signaling override, a ``KeyboardInterrupt`` — used to propagate with the cursor
still open, and ``_serve_db``'s own ``finally`` could not reach it (its local
``cr`` is never assigned when this call raises instead of returning).  The
broad handler closes the cursor on any escape.

Pure-Python: the method is exercised on a minimal stub ``self`` with the
module-level ``Registry`` patched — no HTTP stack, no database.
"""

import typing
import unittest
from types import SimpleNamespace
from unittest import mock

import psycopg

from odoo.http import _serve
from odoo.http.exceptions import RegistryError


class _TrackingCursor:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _acquire(this: typing.Any) -> typing.Any:
    """Call the unbound method with a duck-typed stub ``self`` (cast for mypy)."""
    return _serve._RequestServeMixin._acquire_registry_cursor(this)


def _call(check_signaling):
    """Drive ``_acquire_registry_cursor`` with a registry whose
    ``check_signaling`` behaves as given; return ``(raised, cursor)``.
    """
    cursor = _TrackingCursor()
    registry: typing.Any = SimpleNamespace(
        cursor=lambda readonly=False: cursor,
        check_signaling=check_signaling,
    )
    this = SimpleNamespace(db="testdb", registry=None)
    with mock.patch.object(_serve, "Registry", lambda db: registry):
        raised = None
        try:
            _acquire(this)
        except BaseException as e:  # the test inspects the raised type
            raised = e
    return raised, cursor


class TestAcquireRegistryCursorCleanup(unittest.TestCase):
    def test_success_returns_the_open_cursor(self):
        cursor = _TrackingCursor()
        registry: typing.Any = SimpleNamespace(
            cursor=lambda readonly=False: cursor,
            check_signaling=lambda cr: registry,
        )
        this = SimpleNamespace(db="testdb", registry=None)
        with mock.patch.object(_serve, "Registry", lambda db: registry):
            got = _acquire(this)
        self.assertIs(got, cursor)
        self.assertFalse(cursor.closed)
        self.assertIs(this.registry, registry)

    def test_typed_error_translates_and_closes(self):
        def boom(cr):
            raise psycopg.ProgrammingError("no such column")

        raised, cursor = _call(boom)
        self.assertIsInstance(raised, RegistryError)
        self.assertTrue(cursor.closed, "typed path must close the cursor")

    def test_unexpected_error_closes_and_reraises_unchanged(self):
        sentinel = psycopg.InternalError("catalog is being rebuilt")

        def boom(cr):
            raise sentinel

        raised, cursor = _call(boom)
        # Not translated to RegistryError — propagated as-is …
        self.assertIs(raised, sentinel)
        # … and the cursor is closed rather than leaked.
        self.assertTrue(cursor.closed, "cursor leaked on an unexpected error")

    def test_base_exception_also_closes(self):
        def boom(cr):
            raise KeyboardInterrupt

        raised, cursor = _call(boom)
        self.assertIsInstance(raised, KeyboardInterrupt)
        self.assertTrue(cursor.closed)


if __name__ == "__main__":
    unittest.main()
