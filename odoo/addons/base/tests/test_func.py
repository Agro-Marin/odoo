from odoo import Command
from odoo.tests.common import BaseCase
from odoo.tools import frozendict, lazy


class TestFrozendict(BaseCase):
    def test_frozendict_immutable(self):
        vals = {"name": "Joe", "age": 42}
        frozen_vals = frozendict(vals)

        with self.assertRaises(Exception):
            frozen_vals["surname"] = "Jack"
        with self.assertRaises(Exception):
            frozen_vals["name"] = "Jack"
        with self.assertRaises(Exception):
            del frozen_vals["name"]

        with self.assertRaises(Exception):
            frozen_vals.update({"surname": "Jack"})
        with self.assertRaises(Exception):
            frozen_vals.update({"name": "Jack"})
        with self.assertRaises(Exception):
            frozen_vals.setdefault("surname", "Jack")
        with self.assertRaises(Exception):
            frozen_vals.pop("surname", "Jack")
        with self.assertRaises(Exception):
            frozen_vals.pop("name", "Jack")
        with self.assertRaises(Exception):
            frozen_vals.popitem()
        with self.assertRaises(Exception):
            frozen_vals.clear()

    def test_frozendict_hash(self):
        hash(frozendict({"name": "Joe", "age": 42}))

        hash(
            frozendict(
                {
                    "user_id": (42, "Joe"),
                    "line_ids": [Command.create({"values": [42]})],
                }
            )
        )


class TestLazy(BaseCase):
    def test_lazy_compare(self):
        self.assertEqual(lazy(lambda: 1) <= lazy(lambda: 42), True)
        self.assertEqual(lazy(lambda: 42) <= lazy(lambda: 1), False)
        self.assertEqual(lazy(lambda: 42) == lazy(lambda: 42), True)
        self.assertEqual(lazy(lambda: 1) == lazy(lambda: 42), False)
        self.assertEqual(lazy(lambda: 42) != lazy(lambda: 42), False)
        self.assertEqual(lazy(lambda: 1) != lazy(lambda: 42), True)

        class Obj:
            __hash__ = None

            def __init__(self, num):
                self.num = num

            def __eq__(self, other):
                if isinstance(other, Obj):
                    return self.num == other.num
                msg = "Object does not have the correct type"
                raise ValueError(msg)

        self.assertEqual(lazy(lambda: Obj(42)) == lazy(lambda: Obj(42)), True)
        self.assertEqual(lazy(lambda: Obj(1)) == lazy(lambda: Obj(42)), False)
        self.assertEqual(lazy(lambda: Obj(42)) != lazy(lambda: Obj(42)), False)
        self.assertEqual(lazy(lambda: Obj(1)) != lazy(lambda: Obj(42)), True)
