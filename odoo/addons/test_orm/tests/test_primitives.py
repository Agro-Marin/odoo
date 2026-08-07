from odoo.fields import Command
from odoo.orm.primitives import NewId
from odoo.tests.common import TransactionCase


class TestNewId(TransactionCase):
    def test_bool_is_false(self):
        self.assertFalse(NewId())
        self.assertFalse(NewId(origin=42))
        self.assertFalse(NewId(ref="abc"))
        self.assertIs(bool(NewId()), False)

    def test_eq_same_origin(self):
        a = NewId(origin=1)
        b = NewId(origin=1)
        self.assertEqual(a, b)

    def test_eq_same_ref(self):
        a = NewId(ref="abc")
        b = NewId(ref="abc")
        self.assertEqual(a, b)

    def test_eq_no_match(self):
        a = NewId()
        b = NewId()
        self.assertNotEqual(a, b)

    def test_eq_different_origin(self):
        self.assertNotEqual(NewId(origin=1), NewId(origin=2))

    def test_eq_origin_vs_ref(self):
        a = NewId(origin=1)
        b = NewId(ref=1)
        self.assertNotEqual(a, b)

    def test_eq_not_newid(self):
        self.assertNotEqual(NewId(origin=1), 1)
        self.assertNotEqual(NewId(), None)
        self.assertNotEqual(NewId(ref="x"), "x")

    def test_hash_consistency(self):
        a = NewId(origin=42)
        b = NewId(origin=42)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_hash_in_set(self):
        a = NewId(origin=1)
        b = NewId(origin=1)
        c = NewId(origin=2)
        s = {a, b, c}
        self.assertEqual(len(s), 2)

    def test_hash_in_dict(self):
        a = NewId(origin=1)
        b = NewId(origin=1)
        d = {a: "first"}
        d[b] = "second"
        self.assertEqual(len(d), 1)
        self.assertEqual(d[a], "second")

    def test_hash_bare_unique(self):
        a = NewId()
        b = NewId()
        s = {a, b}
        self.assertEqual(len(s), 2)

    def test_lt_with_int(self):
        self.assertLess(NewId(origin=1), 2)
        self.assertFalse(NewId(origin=2) < 1)

    def test_lt_between_newids(self):
        self.assertLess(NewId(origin=1), NewId(origin=2))
        self.assertFalse(NewId(origin=2) < NewId(origin=1))

    def test_lt_no_origin_vs_int(self):
        self.assertFalse(NewId() < 100)

    def test_lt_origin_vs_none_origin(self):
        self.assertTrue(NewId(origin=5) < NewId())

    def test_lt_none_origin_vs_origin(self):
        self.assertFalse(NewId() < NewId(origin=5))

    def test_lt_both_none_origins(self):
        a = NewId()
        b = NewId()
        self.assertFalse(a < b)

    def test_lt_returns_not_implemented(self):
        result = NewId(origin=1).__lt__("string")
        self.assertIs(result, NotImplemented)

    def test_repr_with_origin(self):
        n = NewId(origin=42)
        self.assertEqual(repr(n), "<NewId origin=42>")

    def test_repr_with_ref(self):
        n = NewId(ref="abc")
        self.assertEqual(repr(n), "<NewId ref='abc'>")

    def test_repr_bare(self):
        n = NewId()
        r = repr(n)
        self.assertTrue(r.startswith("<NewId 0x"))
        self.assertTrue(r.endswith(">"))

    def test_str_with_origin(self):
        n = NewId(origin=42)
        self.assertEqual(str(n), "NewId_42")

    def test_str_with_ref(self):
        n = NewId(ref="abc")
        self.assertEqual(str(n), "NewId_'abc'")

    def test_str_bare(self):
        n = NewId()
        s = str(n)
        self.assertTrue(s.startswith("NewId_0x"))

    def test_total_ordering(self):
        a = NewId(origin=1)
        b = NewId(origin=2)
        self.assertTrue(a < b)
        self.assertTrue(a <= b)
        self.assertTrue(b > a)
        self.assertTrue(b >= a)
        self.assertTrue(a <= NewId(origin=1))
        self.assertTrue(a >= NewId(origin=1))

    def test_eq_origin_set_vs_unset_with_matching_ref(self):
        a = NewId(origin=5, ref="foo")
        b = NewId(origin=None, ref="foo")
        self.assertNotEqual(a, b)
        self.assertIs(a == b, False)

    def test_eq_returns_bool_for_originless_pair(self):
        a = NewId()
        b = NewId()
        self.assertIs(a == b, False)

    def test_no_ordering_contradiction_for_originless(self):
        a = NewId()
        b = NewId()
        self.assertFalse(a > b > a)
        self.assertFalse(a < b < a)

    def test_hash_invariant_under_set(self):
        a = NewId(origin=5, ref="foo")
        b = NewId(origin=5, ref="bar")
        self.assertEqual(a, b)
        self.assertEqual(len({a, b}), 1)

    def test_hash_invariant_under_dict_lookup(self):
        a = NewId(origin=5)
        b = NewId(origin=5, ref="anything")
        self.assertEqual(a, b)
        self.assertEqual({a: "x"}.get(b), "x")

    def test_le_ge_equality_contract_originless_ref(self):
        a = NewId(ref="x")
        b = NewId(ref="x")
        self.assertEqual(a, b)
        self.assertTrue(a <= b)
        self.assertTrue(a >= b)
        self.assertFalse(a < b)
        self.assertFalse(a > b)

    def test_le_ge_equality_contract_same_origin(self):
        a = NewId(origin=42)
        b = NewId(origin=42)
        self.assertEqual(a, b)
        self.assertTrue(a <= b)
        self.assertTrue(a >= b)

    def test_le_ge_distinct_originless_unequal_refs_remain_incomparable(self):
        a = NewId(ref="x")
        b = NewId(ref="y")
        self.assertNotEqual(a, b)
        self.assertFalse(a <= b)
        self.assertFalse(a >= b)
        self.assertFalse(b <= a)
        self.assertFalse(b >= a)

    def test_repr_origin_zero_is_set(self):
        n = NewId(origin=0)
        self.assertEqual(repr(n), "<NewId origin=0>")
        self.assertEqual(str(n), "NewId_0")

    def test_str_origin_takes_precedence_over_ref(self):
        n = NewId(origin=5, ref="abc")
        self.assertEqual(str(n), "NewId_5")
        self.assertEqual(repr(n), "<NewId origin=5>")


class TestCommand(TransactionCase):
    def test_create_tuple(self):
        vals = {"name": "test"}
        result = Command.create(vals)
        self.assertEqual(result, (0, 0, vals))
        self.assertEqual(result[0], Command.CREATE)

    def test_update_tuple(self):
        vals = {"name": "updated"}
        result = Command.update(1, vals)
        self.assertEqual(result, (1, 1, vals))
        self.assertEqual(result[0], Command.UPDATE)

    def test_delete_tuple(self):
        result = Command.delete(5)
        self.assertEqual(result, (2, 5, 0))
        self.assertEqual(result[0], Command.DELETE)

    def test_unlink_tuple(self):
        result = Command.unlink(5)
        self.assertEqual(result, (3, 5, 0))
        self.assertEqual(result[0], Command.UNLINK)

    def test_link_tuple(self):
        result = Command.link(5)
        self.assertEqual(result, (4, 5, 0))
        self.assertEqual(result[0], Command.LINK)

    def test_clear_tuple(self):
        result = Command.clear()
        self.assertEqual(result, (5, 0, 0))
        self.assertEqual(result[0], Command.CLEAR)

    def test_set_tuple(self):
        result = Command.set([1, 2, 3])
        self.assertEqual(result, (6, 0, [1, 2, 3]))
        self.assertEqual(result[0], Command.SET)

    def test_set_empty(self):
        result = Command.set([])
        self.assertEqual(result, (6, 0, []))

    def test_enum_values(self):
        self.assertEqual(Command.CREATE, 0)
        self.assertEqual(Command.UPDATE, 1)
        self.assertEqual(Command.DELETE, 2)
        self.assertEqual(Command.UNLINK, 3)
        self.assertEqual(Command.LINK, 4)
        self.assertEqual(Command.CLEAR, 5)
        self.assertEqual(Command.SET, 6)

    def test_command_is_int_enum(self):
        self.assertIsInstance(Command.CREATE, int)
        self.assertEqual(Command.CREATE + 1, 1)

    def test_command_in_orm_write(self):
        cat1 = self.env["test_orm.category"].create({"name": "Cat 1"})
        cat2 = self.env["test_orm.category"].create({"name": "Cat 2"})
        discussion = self.env["test_orm.discussion"].create(
            {
                "name": "Test Discussion",
                "categories": [Command.link(cat1.id)],
            }
        )
        self.assertEqual(discussion.categories, cat1)

        discussion.write({"categories": [Command.link(cat2.id)]})
        self.assertEqual(discussion.categories, cat1 | cat2)

        discussion.write({"categories": [Command.set(cat2.ids)]})
        self.assertEqual(discussion.categories, cat2)

        discussion.write({"categories": [Command.clear()]})
        self.assertFalse(discussion.categories)


class TestParseFieldExpr(TransactionCase):
    def setUp(self):
        super().setUp()
        from odoo.orm.parsing import parse_field_expr

        parse_field_expr.cache_clear()

    def test_simple(self):
        from odoo.orm.parsing import parse_field_expr

        self.assertEqual(parse_field_expr("amount"), ("amount", None))

    def test_dotted(self):
        from odoo.orm.parsing import parse_field_expr

        self.assertEqual(parse_field_expr("partner_id.name"), ("partner_id", "name"))

    def test_multi_dotted(self):
        from odoo.orm.parsing import parse_field_expr

        self.assertEqual(parse_field_expr("a.b.c"), ("a", "b.c"))

    def test_reject_trailing_dot(self):
        from odoo.orm.parsing import parse_field_expr

        with self.assertRaises(ValueError):
            parse_field_expr("name.")

    def test_reject_double_dot(self):
        from odoo.orm.parsing import parse_field_expr

        with self.assertRaises(ValueError):
            parse_field_expr("x..y")

    def test_reject_leading_dot(self):
        from odoo.orm.parsing import parse_field_expr

        with self.assertRaises(ValueError):
            parse_field_expr(".name")

    def test_reject_empty(self):
        from odoo.orm.parsing import parse_field_expr

        with self.assertRaises(ValueError):
            parse_field_expr("")
