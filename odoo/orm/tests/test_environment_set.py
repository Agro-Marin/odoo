import gc
import unittest
from typing import Any

from odoo.orm.runtime.transaction import _EnvironmentSet


class _FakeEnv:
    __slots__ = ("__weakref__", "context", "su", "uid")

    def __init__(self, uid, su=False, context=()):
        self.uid = uid
        self.su = su
        self.context = context


def _env(uid, su=False, context=()) -> Any:
    return _FakeEnv(uid, su, context)


class TestEnvironmentSet(unittest.TestCase):
    def test_data_is_an_ordered_set_not_a_plain_set(self):
        es = _EnvironmentSet()
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
        es = _EnvironmentSet()
        key = es.key(3, False, ())
        first = _env(3)
        es.add(first)
        second = _env(3)
        es.add(second)
        es.discard(first)
        self.assertIs(es.lookup(key), second)

    def test_iteration_is_sound_while_entries_are_collected(self):
        es = _EnvironmentSet()
        kept = [_env(i) for i in range(50)]
        transient = [_env(1000 + i) for i in range(50)]
        for e in kept + transient:
            es.add(e)
        del transient
        seen = 0
        for _ in es:
            gc.collect()
            seen += 1
        for e in kept:
            self.assertIs(es.lookup(es.key(e.uid, e.su, e.context)), e)
        self.assertGreaterEqual(seen, 0)


if __name__ == "__main__":
    unittest.main()
