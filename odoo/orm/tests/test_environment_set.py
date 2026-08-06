"""Tier-2 tests for ``_EnvironmentSet`` — the WeakSet-with-an-index hack.

Real ``import odoo``, no database.

``Environment.__new__`` reuses an existing environment for the same
``(uid, su, context)``; scanning the live set to find it is O(n) on every
``with_context`` / ``sudo``, so ``_EnvironmentSet`` (``orm/runtime/transaction``)
subclasses ``weakref.WeakSet`` and *replaces its internal ``self.data``* with an
``OrderedSet``, plus a ``WeakValueDictionary`` index for O(1) lookup. Replacing a
CPython-private attribute is version-fragile, and the audit found it had **no
test** — so a point release that reshaped ``WeakSet`` would surface as flaky,
unrelated failures rather than a targeted red here.

These pin the three properties the hack rests on: the index and the set agree,
the index never hands back a *retired* environment (the discard guard), and
iteration stays sound while entries are being garbage-collected.
"""

import gc
import unittest
from typing import Any

from odoo.orm.runtime.transaction import _EnvironmentSet


class _FakeEnv:
    """The surface ``_EnvironmentSet`` reads: uid / su / context, weakref-able."""

    __slots__ = ("__weakref__", "context", "su", "uid")

    def __init__(self, uid, su=False, context=()):
        self.uid = uid
        self.su = su
        self.context = context


def _env(uid, su=False, context=()) -> Any:
    """A duck-typed stand-in for ``Environment``; ``Any`` so the ``add``/
    ``discard``/``lookup`` calls type-check against the real signature."""
    return _FakeEnv(uid, su, context)


class TestEnvironmentSet(unittest.TestCase):
    def test_data_is_an_ordered_set_not_a_plain_set(self):
        es = _EnvironmentSet()
        # The whole point of the hack: deterministic iteration order.
        self.assertEqual(type(es.data).__name__, "OrderedSet")

    def test_insertion_order_is_preserved(self):
        es = _EnvironmentSet()
        envs = [_env(i) for i in range(5)]
        for e in envs:
            es.add(e)
        self.assertEqual(list(es), envs)

    def test_lookup_finds_the_env_by_key(self):
        es = _EnvironmentSet()
        e = _env(7, su=True, context=(("lang", "en"),))
        es.add(e)
        self.assertIs(es.lookup(es.key(7, True, (("lang", "en"),))), e)

    def test_lookup_misses_for_an_unknown_key(self):
        es = _EnvironmentSet()
        es.add(_env(1))
        self.assertIsNone(es.lookup(es.key(2, False, ())))

    def test_a_collected_env_is_gone_from_both_set_and_index(self):
        es = _EnvironmentSet()
        key = es.key(9, False, ())
        e = _env(9)
        es.add(e)
        self.assertIs(es.lookup(key), e)
        del e
        gc.collect()
        self.assertIsNone(es.lookup(key), "the index kept a dead reference")
        self.assertEqual(list(es), [], "the weakset kept a dead reference")

    def test_discard_evicts_only_its_own_index_entry(self):
        """A rebuilt env sharing an old one's key must survive the old's discard.

        The index is keyed on ``(uid, su, context)``, so two environments with
        the same parameters share a bucket; ``discard`` must pop the index entry
        only when it still points at the env being discarded — otherwise
        retiring a duplicate silently retires the live one, and its stale
        ``user``/``company`` cached properties surface as record rules on the
        wrong company (the bug the guard exists to prevent).
        """
        es = _EnvironmentSet()
        key = es.key(3, False, ())
        first = _env(3)
        es.add(first)
        second = _env(3)  # same params, rebuilt
        es.add(second)  # index now points at `second`
        es.discard(first)  # must NOT evict `second`'s index entry
        self.assertIs(es.lookup(key), second)

    def test_iteration_is_sound_while_entries_are_collected(self):
        es = _EnvironmentSet()
        kept = [_env(i) for i in range(50)]
        transient = [_env(1000 + i) for i in range(50)]
        for e in kept + transient:
            es.add(e)
        # Drop the transient strong refs and iterate under GC pressure; the
        # WeakSet's iteration guard must not raise "Set changed size".
        del transient
        seen = 0
        for _ in es:
            gc.collect()
            seen += 1
        # Every surviving env is still reachable via the index.
        for e in kept:
            self.assertIs(es.lookup(es.key(e.uid, e.su, e.context)), e)
        self.assertGreaterEqual(seen, 0)  # no exception is the real assertion


if __name__ == "__main__":
    unittest.main()
