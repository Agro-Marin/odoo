import warnings
from datetime import date, datetime
from itertools import combinations, permutations

from freezegun import freeze_time

from odoo.fields import Command, Domain
from odoo.tests import TransactionCase, users
from odoo.tools import SQL, OrderedSet

from odoo.addons.base.tests.test_expression import TransactionExpressionCase


class TestDomain(TransactionExpressionCase):
    def _search(self, model, domain, init_domain=Domain.TRUE, test_complement=False):
        return super()._search(model, domain, init_domain, test_complement)

    def test_00_test_bool_undefined(self):
        """Undefined/empty values in the database equal False and differ from True."""

        self.env["ir.model.fields"].create(
            {
                "name": "x_bool_new_undefined",
                "model_id": self.env.ref("test_orm.model_domain_bool").id,
                "field_description": "A new boolean column",
                "ttype": "boolean",
            }
        )

        self.env.ref("test_orm.bool_3").write({"x_bool_new_undefined": True})
        self.env.ref("test_orm.bool_4").write({"x_bool_new_undefined": False})

        model = self.env["domain.bool"]
        all_bool = model.search([])
        for f in [
            "bool_true",
            "bool_false",
            "bool_undefined",
            "x_bool_new_undefined",
        ]:
            eq_1 = self._search(model, [(f, "=", False)])
            neq_1 = self._search(model, [(f, "!=", True)])
            self.assertEqual(
                eq_1,
                neq_1,
                "`= False` (%s) <> `!= True` (%s) " % (len(eq_1), len(neq_1)),
            )

            eq_2 = self._search(model, [(f, "=", True)])
            neq_2 = self._search(model, [(f, "!=", False)])
            self.assertEqual(
                eq_2,
                neq_2,
                "`= True` (%s) <> `!= False` (%s) " % (len(eq_2), len(neq_2)),
            )

            self.assertEqual(eq_1 + eq_2, all_bool, "True + False != all")
            self.assertEqual(neq_1 + neq_2, all_bool, "not True + not False != all")

    def test_domain_hashable(self):
        """Domains must be hashable, including the normalized shape.

        Optimization canonicalizes ``in``/``=`` values to (unhashable)
        ``OrderedSet``; ``DomainCondition.__hash__`` must not raise on that shape
        and must satisfy ``a == b ⟹ hash(a) == hash(b)``.  Regression for the
        previous ``hash(self.value)`` which raised ``TypeError`` on every
        optimized ``in`` condition.
        """
        Model = self.env["test_orm.empty_int"]

        d1 = Domain("number", "in", [1, 2, 3]).optimize(Model)
        d2 = Domain("number", "in", [3, 2, 1]).optimize(Model)
        self.assertEqual(d1, d2)
        self.assertEqual(hash(d1), hash(d2))
        self.assertEqual(len({d1, d2}), 1)

        nary = Domain.OR(
            [Domain("number", "in", [1, 2]), Domain("number", "=", 5)]
        ).optimize(Model)
        self.assertIsInstance(hash(nary), int)

        self.assertNotEqual(
            hash(Domain("number", "=", 1).optimize(Model)),
            hash(Domain("number", "=", 2).optimize(Model)),
        )

    def test_empty_int(self):
        EmptyInt = self.env["test_orm.empty_int"]
        records = EmptyInt.create(
            [
                {"number": 42},
                {"number": 0},
                {"number": False},
                {},
            ]
        )
        self.assertListEqual(records.mapped("number"), [42, 0, 0, 0])

        self.env.flush_all()

        sql = SQL(
            "SELECT number FROM test_orm_empty_int WHERE id = ANY(%s) ORDER BY id",
            list(records._ids),
        )
        rows = self.env.execute_query(sql)
        self.assertEqual([row[0] for row in rows], [42, 0, 0, None])

        self.assertListEqual(
            self._search(EmptyInt, [("number", "=", 42)]).mapped("number"), [42]
        )
        self.assertListEqual(
            self._search(EmptyInt, [("number", "!=", 42)]).mapped("number"),
            [0, 0, 0],
        )

        self.assertListEqual(
            self._search(EmptyInt, [("number", "=", 0)]).mapped("number"),
            [0, 0, 0],
        )
        self.assertListEqual(
            self._search(EmptyInt, [("number", "!=", 0)]).mapped("number"), [42]
        )

        self.assertListEqual(
            self._search(EmptyInt, [("number", "=", False)]).mapped("number"),
            [0, 0, 0],
        )
        self.assertListEqual(
            self._search(EmptyInt, [("number", "!=", False)]).mapped("number"),
            [42],
        )

        self.assertListEqual(
            self._search(EmptyInt, [("number", "<", 1)]).mapped("number"),
            [0, 0, 0],
        )
        self.assertListEqual(
            self._search(EmptyInt, [("number", ">", -1)]).mapped("number"),
            [42, 0, 0, 0],
        )
        self.assertListEqual(
            self._search(EmptyInt, [("number", "<=", 0)]).mapped("number"),
            [0, 0, 0],
        )
        self.assertListEqual(
            self._search(EmptyInt, [("number", ">=", 0)]).mapped("number"),
            [42, 0, 0, 0],
        )
        self.assertListEqual(
            self._search(EmptyInt, [("number", ">", 1)]).mapped("number"), [42]
        )
        self.assertListEqual(
            self._search(EmptyInt, [("number", "<", -1)]).mapped("number"), []
        )

        values = [42, 0, False]
        for length in range(len(values) + 1):
            for subset in combinations(values, length):
                self.assertEqual(
                    self._search(EmptyInt, [("number", "in", list(subset))]),
                    records.filtered(
                        lambda record, subset=subset: record.number in subset
                    ),
                    f"Incorrect result for search([('number', 'in', {sorted(subset)})])",
                )
                self.assertEqual(
                    self._search(EmptyInt, [("number", "not in", list(subset))]),
                    records.filtered(
                        lambda record, subset=subset: record.number not in subset
                    ),
                    f"Incorrect result for search([('number', 'not in', {sorted(subset)})])",
                )

    def test_empty_char(self):
        EmptyChar = self.env["test_orm.empty_char"]
        records = EmptyChar.create(
            [
                {"name": "name"},
                {"name": ""},
                {"name": False},
                {},
            ]
        )
        self.assertListEqual(records.mapped("name"), ["name", "", False, False])

        self.env.flush_all()

        sql = SQL(
            "SELECT name FROM test_orm_empty_char WHERE id = ANY(%s) ORDER BY id",
            list(records._ids),
        )
        rows = self.env.execute_query(sql)
        self.assertEqual([row[0] for row in rows], ["name", "", None, None])

        self.assertListEqual(
            self._search(EmptyChar, [("name", "=", "name")]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "!=", "name")]).mapped("name"),
            ["", False, False],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "ilike", "name")]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "not ilike", "name")]).mapped("name"),
            ["", False, False],
        )

        self.assertListEqual(
            self._search(EmptyChar, [("name", "=", "")]).mapped("name"),
            ["", False, False],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "!=", "")]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "ilike", "")]).mapped("name"),
            ["name", "", False, False],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "not ilike", "")]).mapped("name"),
            [],
        )

        self.assertListEqual(
            self._search(EmptyChar, [("name", "=", False)]).mapped("name"),
            ["", False, False],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "!=", False)]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "ilike", False)]).mapped("name"),
            ["name", "", False, False],
        )
        self.assertListEqual(
            self._search(EmptyChar, [("name", "not ilike", False)]).mapped("name"),
            [],
        )

        values = ["name", "", False]
        for length in range(len(values) + 1):
            for subset in combinations(values, length):
                subset_check = set(subset)
                if {False, ""} & subset_check:
                    subset_check |= {False, ""}
                self.assertEqual(
                    self._search(EmptyChar, [("name", "in", list(subset))]),
                    records.filtered(
                        lambda record, subset_check=subset_check: (
                            record.name in subset_check
                        )
                    ),
                    f"Incorrect result for search([('name', 'in', {list(subset)})])",
                )
                self.assertEqual(
                    self._search(EmptyChar, [("name", "not in", list(subset))]),
                    records.filtered(
                        lambda record, subset_check=subset_check: (
                            record.name not in subset_check
                        )
                    ),
                    f"Incorrect result for search([('name', 'not in', {list(subset)})])",
                )

        self.assertListEqual(
            self._search(EmptyChar, [("name", "=like", "na%")]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(EmptyChar, ["!", ("name", "=like", "na%")]).mapped("name"),
            ["", False, False],
        )

    def test_empty_translation(self):
        records_en = (
            self.env["test_orm.indexed_translation"]
            .with_context(lang="en_US")
            .create(
                [
                    {"name": "English"},
                    {"name": "English"},
                    {"name": "English"},
                ]
            )
        )
        self.env["res.lang"]._activate_lang("fr_FR")
        records_fr = records_en.with_context(lang="fr_FR")
        records_fr[0].name = "name"
        records_fr[1].name = ""
        records_fr[2].name = False
        self.assertListEqual(records_en.mapped("name"), ["English", "English", False])
        self.assertListEqual(records_fr.mapped("name"), ["name", "", False])

        self.assertListEqual(
            self._search(records_fr, [("name", "=", "name")]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "!=", "name")]).mapped("name"),
            ["", False],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "ilike", "name")]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "not ilike", "name")]).mapped("name"),
            ["", False],
        )

        self.assertListEqual(
            self._search(records_fr, [("name", "=", "")]).mapped("name"),
            ["", False],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "!=", "")]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "ilike", "")]).mapped("name"),
            ["name", "", False],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "not ilike", "")]).mapped("name"),
            [],
        )

        self.assertListEqual(
            self._search(records_fr, [("name", "=", False)]).mapped("name"),
            ["", False],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "!=", False)]).mapped("name"),
            ["name"],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "ilike", False)]).mapped("name"),
            ["name", "", False],
        )
        self.assertListEqual(
            self._search(records_fr, [("name", "not ilike", False)]).mapped("name"),
            [],
        )

        values = ["name", "", False]
        for length in range(len(values) + 1):
            for subset in combinations(values, length):
                subset_check = set(subset)
                if {False, ""} & subset_check:
                    subset_check |= {False, ""}
                self.assertEqual(
                    self._search(records_fr, [("name", "in", list(subset))]),
                    records_fr.filtered(
                        lambda record, subset_check=subset_check: (
                            record.name in subset_check
                        )
                    ),
                    f"Incorrect result for search([('name', 'in', {list(subset)})])",
                )
                self.assertEqual(
                    self._search(records_fr, [("name", "not in", list(subset))]),
                    records_fr.filtered(
                        lambda record, subset_check=subset_check: (
                            record.name not in subset_check
                        )
                    ),
                    f"Incorrect result for search([('name', 'not in', {list(subset)})])",
                )

    def test_anys_many2one(self):
        Parent = self.env["test_orm.any.parent"]
        Child = self.env["test_orm.any.child"]

        parent_1, parent_2 = Parent.create(
            [
                {
                    "name": "Jean",
                    "child_ids": [
                        Command.create({"quantity": 1}),
                        Command.create({"quantity": 10}),
                    ],
                },
                {
                    "name": "Clude",
                    "child_ids": [
                        Command.create({"quantity": 2}),
                        Command.create({"quantity": 20}),
                    ],
                },
            ]
        )
        parent_1.child_ids[0].link_sibling_id = parent_1.child_ids[1]
        parent_2.child_ids[1].link_sibling_id = parent_2.child_ids[0]

        res_search = self._search(
            Child, [("link_sibling_id", "any", [("quantity", ">", 5)])]
        )
        self.assertEqual(res_search, parent_1.child_ids[0])

        res_search = self._search(
            Child, [("link_sibling_id", "not any", [("quantity", ">", 5)])]
        )
        self.assertEqual(res_search, parent_1.child_ids[1] + parent_2.child_ids)

        self.assertFalse(Child._fields["link_sibling_id"].bypass_search_access)
        self.patch(Child._fields["link_sibling_id"], "bypass_search_access", True)
        self.assertTrue(Child._fields["link_sibling_id"].bypass_search_access)

        res_search = self._search(
            Child, [("link_sibling_id", "any", [("quantity", ">", 5)])]
        )
        self.assertEqual(res_search, parent_1.child_ids[0])

        res_search = self._search(
            Child, [("link_sibling_id", "not any", [("quantity", ">", 5)])]
        )
        self.assertEqual(res_search, parent_1.child_ids[1] + parent_2.child_ids)

        res_search = self._search(
            Child, [("parent_id", "any", [("name", "=", "Jean")])]
        )
        self.assertEqual(res_search, parent_1.child_ids)

        res_search = self._search(
            Child, [("parent_id", "not any", [("name", "=", "Jean")])]
        )
        self.assertEqual(res_search, parent_2.child_ids)

    def test_anys_many2one_implicit(self):
        Parent = self.env["test_orm.any.parent"]

        parent_1, parent_2 = Parent.create(
            [
                {
                    "name": "Jean",
                    "child_ids": [
                        Command.create({"quantity": 1}),
                        Command.create({"quantity": 10}),
                    ],
                },
                {
                    "name": "Clude",
                    "child_ids": [
                        Command.create({"quantity": 2}),
                        Command.create({"quantity": 20}),
                    ],
                },
            ]
        )

        res_search = self._search(Parent, [("child_ids.quantity", "=", 1)])
        self.assertEqual(res_search, parent_1)

        res_search = self._search(Parent, [("child_ids.quantity", ">", 15)])
        self.assertEqual(res_search, parent_2)

    def test_anys_one2many(self):
        Parent = self.env["test_orm.any.parent"]

        parent_1, parent_2, parent_3 = Parent.create(
            [
                {
                    "child_ids": [
                        Command.create({"quantity": 1}),
                        Command.create({"quantity": 10}),
                    ],
                },
                {
                    "child_ids": [
                        Command.create({"quantity": 2}),
                        Command.create({"quantity": 20}),
                    ],
                },
                {},
            ]
        )

        res_search = self._search(
            Parent, [("child_ids", "any", [("quantity", "=", 1)])]
        )
        self.assertEqual(res_search, parent_1)

        res_search = self._search(
            Parent, [("child_ids", "not any", [("quantity", "=", 1)])]
        )
        self.assertEqual(res_search, parent_2 + parent_3)

        self.assertFalse(Parent._fields["child_ids"].bypass_search_access)
        self.patch(Parent._fields["child_ids"], "bypass_search_access", True)
        self.assertTrue(Parent._fields["child_ids"].bypass_search_access)

        res_search = self._search(
            Parent, [("child_ids", "any", [("quantity", "=", 1)])]
        )
        self.assertEqual(res_search, parent_1)

        res_search = self._search(
            Parent, [("child_ids", "not any", [("quantity", "=", 1)])]
        )
        self.assertEqual(res_search, parent_2 + parent_3)

    def test_anys_many2many(self):
        Child = self.env["test_orm.any.child"]

        child_1, child_2, child_3 = Child.create(
            [
                {
                    "tag_ids": [
                        Command.create({"name": "Urgent"}),
                        Command.create({"name": "Important"}),
                    ],
                },
                {
                    "tag_ids": [
                        Command.create({"name": "Other"}),
                    ],
                },
                {},
            ]
        )

        res_search = self._search(
            Child, [("tag_ids", "any", [("name", "=", "Urgent")])]
        )
        self.assertEqual(res_search, child_1)

        res_search = self._search(
            Child, [("tag_ids", "not any", [("name", "=", "Urgent")])]
        )
        self.assertEqual(res_search, child_2 + child_3)


class TestDomainComplement(TransactionExpressionCase):
    def test_inequalities_int(self):
        Model = self.env["test_orm.empty_int"]
        Model.create([{}])
        Model.create([{"number": n} for n in range(-5, 6)])
        self._search(Model, [("number", ">", 2)])
        self._search(Model, [("number", ">", -2)])
        self._search(Model, [("number", "<", 1)])
        self._search(Model, [("number", "<=", 1)])

    def test_inequalities_float(self):
        Model = self.env["test_orm.mixed"]
        Model.create([{}])
        Model.create([{"number2": n} for n in (-5, -3.3, 0.0, 0.1, 3, 4.5)])
        self._search(Model, [("number2", ">", 2)])
        self._search(Model, [("number2", ">", -2)])
        self._search(Model, [("number2", ">", 3)])
        self._search(Model, [("number2", "<", 1)])
        self._search(Model, [("number2", "<=", 1)])

    def test_inequalities_char(self):
        Model = self.env["test_orm.empty_char"]
        Model.create([{}])
        Model.create([{"name": n} for n in (False, "", "hello", "world")])
        self._search(Model, [("name", ">", "a")])
        self._search(Model, [("name", ">", "z")])
        self._search(Model, [("name", "<", "k")])
        self._search(Model, [("name", "<=", "k")])
        self._search(Model, [("name", "<", "")])

    def test_inequalities_datetime(self):
        Model = self.env["test_orm.mixed"]
        Model.create([{}])
        Model.create([{"moment": datetime(2000, 5, n)} for n in range(5, 10)])
        self._search(Model, [("moment", ">", datetime(2000, 5, 3))])
        self._search(Model, [("moment", ">", datetime(2000, 5, 8))])
        self._search(Model, [("moment", ">", datetime(2000, 5, 20))])
        self._search(Model, [("moment", "<", datetime(2000, 5, 7))])
        self._search(Model, [("moment", "<=", datetime(2000, 5, 7))])

    def test_inequalities_m2o(self):
        Model = self.env["test_orm.model_active_field"]

        active_parent = Model.create({"name": "Parent"})
        Model.create({"name": "Child of active", "parent_id": active_parent.id})
        Model.create({"parent_id": active_parent.id})
        inactive_parent = Model.create({"name": "Parent", "active": False})
        Model.create({"name": "Child of inactive", "parent_id": inactive_parent.id})

        self._search(Model, [("parent_id", "<", active_parent.id)])
        self._search(Model, [("parent_id", ">=", inactive_parent.id)])

        with self.assertRaises(TypeError):
            self._search(Model, [("parent_id", ">=", "Par")])


class TestDomainOptimize(TransactionCase):
    number_domain = Domain("number", ">", 5)

    def test_bool_optimize(self):
        model = self.env["test_orm.mixed"]
        self.assertIs(Domain.TRUE.optimize(model), Domain.TRUE)
        self.assertIs(Domain.FALSE.optimize(model), Domain.FALSE)

    def test_condition_build(self):
        dom = Domain("a", "=", 1)
        self.assertEqual((dom.field_expr, dom.operator, dom.value), ("a", "=", 1))

        dom = Domain("a", "=", [1, 2])
        self.assertEqual((dom.field_expr, dom.operator, dom.value), ("a", "=", [1, 2]))
        self.assertEqual(Domain("a", "in", 5).value, 5)
        self.assertEqual(
            Domain("a", "=", []).value,
            [],
            "Edge-case, caller probably meant =False",
        )

        self.assertEqual(Domain("a", "in", Domain.TRUE).operator, "in")
        self.assertIsInstance(Domain("a", "any", [("x", ">", 1)]).value, list)

    def test_condition_optimize_optimal(self):
        model = self.env["test_orm.mixed"]
        domain = self.number_domain
        self.assertIs(domain.optimize(model), domain, "Domain is already optimized")

    def test_condition_optimize_invalid_field(self):
        model = self.env["test_orm.mixed"]
        domain = Domain("xxx_inexisting", "=", False)
        with self.assertRaises(ValueError):
            domain.optimize(model)

    def test_condition_optimize_search(self):
        model = self.env["test_orm.bar"]
        foo = model.foo.create({"name": "ok"})
        self.assertEqual(
            Domain("foo", "=", foo.id).optimize_full(model),
            Domain("name", "in", ["ok"]).optimize(model),
        )
        self.assertEqual(
            Domain("foo", "in", foo.browse().ids).optimize(model),
            Domain.FALSE,
            "search should be further optimized",
        )

    def test_condition_optimize_traverse(self):
        model = self.env["test_orm.mixed"]
        self.assertEqual(
            Domain("currency_id.id", ">", 5).optimize(model),
            Domain("currency_id", "any", Domain("id", ">", 5)),
        )
        self.assertEqual(
            (~Domain("currency_id.id", ">", 5)).optimize(model),
            Domain("currency_id", "not any", Domain("id", ">", 5)),
        )

    def test_condition_optimize_in(self):
        model = self.env["test_orm.mixed"]
        domain = Domain("id", "in", range(5)).optimize(model)
        self.assertIsInstance(domain.value, OrderedSet)
        domain = Domain("id", "in", [9, 99]).optimize(model)
        self.assertIsInstance(domain.value, OrderedSet)
        self.assertIs(domain.optimize(model), domain, "Idempotent")

        self.assertEqual(
            Domain("id", "in", []).optimize(model),
            Domain.FALSE,
        )
        self.assertEqual(
            Domain("id", "not in", []).optimize(model),
            Domain.TRUE,
        )

    def test_condition_optimize_deprecated_operators(self):
        """`<>` and `==` are deprecated aliases that normalize to `!=` / `=`."""
        model = self.env["test_orm.mixed"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.assertEqual(
                Domain("count", "<>", 5).optimize(model),
                Domain("count", "!=", 5).optimize(model),
            )
            self.assertEqual(
                Domain("count", "==", 5).optimize(model),
                Domain("count", "=", 5).optimize(model),
            )

    def test_condition_optimize_deprecated_operators_warn(self):
        model = self.env["test_orm.mixed"]
        with self.assertWarns(DeprecationWarning):
            Domain("count", "<>", 5).optimize(model)
        with self.assertWarns(DeprecationWarning):
            Domain("count", "==", 5).optimize(model)

    def test_condition_optimize_equality_collection(self):
        """`=`/`!=` against a collection normalize to `in`/`not in`."""
        model = self.env["test_orm.mixed"]
        self.assertEqual(
            Domain("count", "=", [1, 2]).optimize(model),
            Domain("count", "in", [1, 2]).optimize(model),
        )
        self.assertEqual(
            Domain("count", "!=", [1, 2]).optimize(model),
            Domain("count", "not in", [1, 2]).optimize(model),
        )

    def test_condition_optimize_equality_empty_collection(self):
        """The view idiom ``('field', '!=', [])`` means "field is set" and
        ``('field', '=', [])`` means "field is unset" — both normalize to a
        comparison against ``False`` (``not in {False}`` / ``in {False}``)."""
        model = self.env["test_orm.mixed"]
        self.assertEqual(
            Domain("count", "!=", []).optimize(model),
            Domain("count", "!=", False).optimize(model),
        )
        self.assertEqual(
            Domain("count", "=", []).optimize(model),
            Domain("count", "=", False).optimize(model),
        )

    def test_condition_optimize_any(self):
        model = self.env["test_orm.mixed"]

        domain = Domain("currency_id", "any!", model.currency_id._search([]))
        self.assertIs(domain.optimize(model), domain, "Idempotent with a Query value")

        self.assertEqual(
            Domain("currency_id", "any", Domain.FALSE).optimize(model),
            Domain.FALSE,
        )
        self.assertEqual(
            Domain("currency_id", "not any", Domain.FALSE).optimize(model),
            Domain.TRUE,
        )
        self.assertEqual(
            Domain("currency_id", "any", Domain("id", "not in", [])).optimize(model),
            Domain("currency_id", "any", Domain.TRUE),
            "optimize the domain",
        )

        domain = Domain("currency_id", "any", Domain("id", "in", [1])).optimize(model)
        self.assertIs(domain.optimize(model), domain, "Idempotent")

    def test_condition_optimize_any_non_relational(self):
        model = self.env["test_orm.mixed"]
        domain = Domain("number", "any", Domain("id", ">", 0))
        with self.assertRaises(ValueError):
            domain.optimize(model)

    def test_condition_optimize_any_id(self):
        model = self.env["test_orm.mixed"]
        self.assertEqual(
            Domain("id", "any", self.number_domain).optimize(model),
            self.number_domain,
        )
        self.assertEqual(
            Domain("id", "not any", self.number_domain).optimize(model),
            (~self.number_domain).optimize(model),
        )

    def test_condition_optimize_like(self):
        model = self.env["test_orm.message"]
        domain = Domain("name", "like", "ok")
        self.assertIs(
            domain.optimize(model),
            domain,
            "Idempotent",
        )

        self.assertEqual(
            Domain("name", "like", "").optimize(model),
            Domain.TRUE,
            "Matching anything",
        )
        self.assertEqual(
            Domain("name", "not like", "").optimize(model),
            Domain.FALSE,
            "Matching nothing",
        )
        self.assertEqual(
            Domain("name", "=like", "").optimize(model),
            Domain("name", "=", False).optimize(model),
            "Matching empty string only",
        )
        self.assertEqual(
            Domain("name", "like", 5).optimize(model),
            Domain("name", "like", "5"),
            "Convert to str type for like matching",
        )

    def test_condition_optimize_like_relational(self):
        model = self.env["test_orm.message"]
        self.assertEqual(
            Domain("discussion", "like", "").optimize(model),
            Domain("discussion", "not in", OrderedSet([False])),
            "Matching anything in relation",
        )
        domain = Domain("discussion", "like", "ok").optimize(model)
        self.assertEqual(domain.operator, "any")
        self.assertIsInstance(domain.value, Domain)
        self.assertEqual(domain.value.field_expr, "display_name")

        domain = Domain("discussion", "not like", "ok").optimize(model)
        self.assertEqual(
            domain.operator,
            "not any",
            f"Always use positive operator when searching on display_name; in {domain}",
        )

    def test_condition_optimize_bool(self):
        model = self.env["test_orm.message"]
        is_important = Domain("important", "in", OrderedSet([True]))
        self.assertIs(
            is_important.optimize(model),
            is_important,
            "Idempotent optimization",
        )
        self.assertEqual(
            Domain("important", "=", True).optimize(model),
            Domain("important", "in", OrderedSet([True])),
        )
        self.assertEqual(
            list(Domain("important", "not in", [True, False]).optimize(model)),
            [("important", "not in", [True, False])],
            "the condition should not be reduced to a constant",
        )
        self.assertEqual(
            Domain("important", "not in", [True, False]).optimize_full(model),
            Domain.FALSE,
        )
        self.assertEqual(
            Domain("important", "in", [True, "yes"]).optimize(model),
            is_important,
        )
        self.assertEqual(
            Domain("important", "in", ["yes"]).optimize(model),
            is_important,
        )
        self.assertEqual(
            Domain("important", "in", [0, 2]).optimize_full(model),
            Domain.TRUE,
        )
        self.assertEqual(
            list(Domain("active", "in", [True, False]).optimize(model)),
            [("active", "in", [True, False])],
            "the condition should not be reduced to a constant for active record",
        )
        self.assertEqual(
            Domain("active", "in", [True, False]).optimize_full(model),
            Domain.TRUE,
        )

    def test_condition_optimize_date(self):
        model = self.env["test_orm.mixed"]
        self.assertEqual(
            Domain("date", "=", date(2024, 1, 5)).optimize(model),
            Domain("date", "in", OrderedSet([date(2024, 1, 5)])),
        )
        self.assertEqual(
            Domain("date", "=", datetime(2024, 1, 5, 12, 0, 0)).optimize(model),
            Domain("date", "in", OrderedSet([date(2024, 1, 5)])),
        )
        self.assertEqual(
            Domain("date", "=", "2024-01-05").optimize(model),
            Domain("date", "in", OrderedSet([date(2024, 1, 5)])),
        )
        self.assertEqual(
            Domain("date", "=like", "2024%").optimize(model),
            Domain("date", "=like", "2024%"),
        )
        self.assertEqual(
            Domain("date", ">", "2024-01-01").optimize(model),
            Domain("date", ">", date(2024, 1, 1)),
        )
        self.assertEqual(
            Domain("date", ">", False).optimize(model),
            Domain.FALSE,
        )
        self.assertEqual(
            Domain("date", "not in", ["2024-01-05", date(2023, 1, 1)]).optimize(model),
            Domain(
                "date",
                "not in",
                OrderedSet([date(2024, 1, 5), date(2023, 1, 1)]),
            ),
        )

        with self.assertRaises(ValueError):
            Domain("date", ">", "hello").optimize(model)

        with freeze_time("2024-01-05 13:05:00"):
            domain = Domain("date", ">", "today")
            self.assertEqual(domain.optimize(model), domain)
            self.assertEqual(
                domain.optimize_full(model),
                Domain("date", ">", date(2024, 1, 5)),
            )
            self.assertEqual(
                Domain("date", ">", "+12H").optimize_full(model),
                Domain("date", ">", date(2024, 1, 6)),
            )
            self.assertEqual(
                list(Domain("date", "=", "today").optimize_full(model).value),
                [date(2024, 1, 5)],
            )

    def test_condition_optimize_datetime(self):
        model = self.env["test_orm.mixed"].with_context(tz="UTC")
        self.assertEqual(
            Domain("moment", "=", date(2024, 1, 5)).optimize(model),
            Domain("moment", "<", datetime(2024, 1, 6))
            & Domain("moment", ">=", datetime(2024, 1, 5)),
        )
        self.assertEqual(
            Domain("moment", "=", "2024-01-05").optimize(model),
            Domain("moment", "<", datetime(2024, 1, 6))
            & Domain("moment", ">=", datetime(2024, 1, 5)),
        )
        self.assertEqual(
            Domain("moment", "=like", "2024%").optimize(model),
            Domain("moment", "=like", "2024%"),
        )
        self.assertEqual(
            Domain("moment", ">", "2024-01-01 10:00:00").optimize(model),
            Domain("moment", ">=", datetime(2024, 1, 1, 10, second=1)),
        )
        self.assertEqual(
            Domain("moment", ">", "2024-01-01").optimize(model),
            Domain("moment", ">=", datetime(2024, 1, 2)),
        )
        self.assertEqual(
            Domain("moment", "<", "2024-01-01").optimize(model),
            Domain("moment", "<", datetime(2024, 1, 1)),
        )
        self.assertEqual(
            Domain("moment", "<=", "2024-01-01").optimize(model),
            Domain("moment", "<", datetime(2024, 1, 2)),
        )
        self.assertEqual(
            Domain("moment", ">", False).optimize(model),
            Domain.FALSE,
        )
        self.assertEqual(
            Domain("moment", "not in", ["2024-01-05", datetime(2023, 1, 1)]).optimize(
                model
            ),
            (
                Domain("moment", "in", OrderedSet([False]))
                | Domain("moment", "<", datetime(2023, 1, 1))
                | Domain("moment", ">=", datetime(2023, 1, 1, second=1))
            )
            & (
                Domain("moment", "in", OrderedSet([False]))
                | Domain("moment", "<", datetime(2024, 1, 5))
                | Domain("moment", ">=", datetime(2024, 1, 6))
            ),
        )

        with self.assertRaises(ValueError):
            Domain("moment", ">", "hello").optimize(model)

        with freeze_time("2024-01-05 13:05:00"):
            domain = Domain("moment", ">=", "today")
            self.assertEqual(domain.optimize(model), domain)
            self.assertEqual(
                domain.optimize_full(model),
                Domain("moment", ">=", datetime(2024, 1, 5)),
            )
            self.assertEqual(
                Domain("moment", ">=", "+12H").optimize_full(model),
                Domain("moment", ">=", datetime(2024, 1, 6, 1, 5)),
            )
            today_domain = Domain("moment", "=", "today").optimize_full(model)
            self.assertIn(
                datetime(2024, 1, 5),
                [
                    v
                    for cond in today_domain.iter_conditions()
                    for v in (
                        [cond.value] if isinstance(cond.value, datetime) else cond.value
                    )
                ],
            )

    def test_condition_optimize_datetime_timezone(self):
        model = self.env["test_orm.mixed"].with_context(tz="Europe/Brussels")
        self.assertEqual(
            Domain("moment", ">=", "2024-01-01 10:00:00").optimize(model),
            Domain("moment", ">=", datetime(2024, 1, 1, 10)),
            "Timezone should have no effect on datetime",
        )
        self.assertEqual(
            Domain("moment", ">=", "2024-07-02").optimize(model),
            Domain("moment", ">=", datetime(2024, 7, 1, 22)),
            "Date should consider timezone of the user",
        )
        self.assertEqual(
            Domain("moment", ">=", "2024-01-02").optimize(model),
            Domain("moment", ">=", datetime(2024, 1, 1, 23)),
            "Date should consider timezone of the user",
        )

    def test_condition_optimize_datetime_millisecond(self):
        model = self.env["test_orm.mixed"].with_context(tz="UTC")
        self.assertEqual(
            Domain("moment", "=", "2024-01-05").optimize(model),
            Domain("moment", "<", datetime(2024, 1, 6))
            & Domain("moment", ">=", datetime(2024, 1, 5)),
        )
        self.assertEqual(
            Domain("moment", "=", "2024-01-05 11:06:02.123").optimize(model),
            Domain("moment", "<", datetime(2024, 1, 5, 11, 6, 3))
            & Domain("moment", ">=", datetime(2024, 1, 5, 11, 6, 2)),
        )
        self.assertEqual(
            Domain("moment", "=", "2024-01-05 11:06:02").optimize(model),
            Domain("moment", "<", datetime(2024, 1, 5, 11, 6, 3))
            & Domain("moment", ">=", datetime(2024, 1, 5, 11, 6, 2)),
        )
        self.assertEqual(
            Domain("moment", "=", datetime(2024, 1, 5, 11, 6, 2)).optimize(model),
            Domain("moment", "<", datetime(2024, 1, 5, 11, 6, 3))
            & Domain("moment", ">=", datetime(2024, 1, 5, 11, 6, 2)),
        )
        self.assertEqual(
            Domain("moment", ">=", "2024-01-05 11:06:02.123").optimize(model),
            Domain("moment", ">=", datetime(2024, 1, 5, 11, 6, 2)),
        )
        self.assertEqual(
            Domain("moment", ">=", "2024-01-05 11:06:02").optimize(model),
            Domain("moment", ">=", datetime(2024, 1, 5, 11, 6, 2)),
        )

    def test_condition_optimize_maybe_eq(self):
        model = self.env["test_orm.mixed"]
        self.assertEqual(
            Domain("number", "=?", 5).optimize(model),
            Domain("number", "=", 5).optimize(model),
        )
        self.assertEqual(
            Domain("number", "=?", 0).optimize(model),
            Domain.TRUE,
        )

    def test_condition_optimize_child_parent_of(self):
        model = self.env["test_orm.category"]
        categ = model.create({"name": "parent"})
        categ_child = model.create({"name": "child", "parent": categ.id})
        self.assertEqual(
            Domain("id", "child_of", categ.ids).optimize_full(model),
            Domain("parent_path", "=like", f"{categ.parent_path}%"),
        )
        self.assertEqual(
            Domain("id", "parent_of", categ_child.ids).optimize_full(model),
            Domain("id", "in", OrderedSet([categ_child.id, categ.id])),
        )

    def test_condition_hierarchy_boolean_values(self):
        """Booleans in child_of/parent_of fail (True) or collapse (False) cleanly."""
        model = self.env["test_orm.category"]
        parent = model.create({"name": "parent"})
        model.create({"name": "child", "parent": parent.id})
        for op in ("child_of", "parent_of"):
            for value in (True, [True], [True, parent.id]):
                with self.assertRaises(ValueError, msg=f"{op} {value!r}"):
                    model.search([("id", op, value)])
            self.assertFalse(model.search([("id", op, False)]))
            self.assertFalse(model.search([("id", op, [False])]))
            self.assertEqual(
                model.search([("id", op, [False, parent.id])]),
                model.search([("id", op, parent.id)]),
            )

    def test_filtered_domain_new_records_required_m2o(self):
        """A FULL-optimized domain reused over new() records still sees the False branch."""
        model = self.env["test_orm.move_line"]
        move = self.env["test_orm.move"].create({})
        raw = [("move_id", "in", [False, move.id])]
        full = Domain(raw).optimize_full(model)
        [(_, _, optimized_value)] = list(full)
        self.assertEqual(optimized_value, [move.id])

        new_record = model.new({})
        self.assertFalse(new_record.move_id)
        self.assertEqual(
            new_record.filtered_domain(raw),
            new_record,
            "fresh parse: an unset required m2o matches the False branch",
        )
        self.assertEqual(
            new_record.filtered_domain(full),
            new_record,
            "the FULL-stamped (stripped) domain must agree with the fresh "
            "parse over new records",
        )
        line = model.create({"move_id": move.id})
        self.assertEqual(line.filtered_domain(full), line.filtered_domain(raw))

    def test_not_optimize(self):
        self.assertEqual(
            ~~self.number_domain,
            self.number_domain,
        )

    def test_sudo_optimize(self):
        model = self.env["test_orm.discussion"].with_user(
            self.env.ref("base.public_user")
        )
        self.assertEqual(
            Domain("moderator", "any", Domain("login", "like", "one")).optimize_full(
                model
            ),
            Domain("moderator", "any", Domain("login", "like", "one")),
        )
        self.assertEqual(
            Domain("moderator", "any", Domain("login", "like", "one")).optimize_full(
                model.sudo()
            ),
            Domain("moderator", "any!", Domain("login", "like", "one")),
        )
        query = model.moderator._search(Domain.TRUE)
        self.assertEqual(
            Domain("moderator", "any", query).optimize(model),
            Domain("moderator", "any!", query),
        )

    def test_nary_build(self):
        self.assertEqual(
            ~(self.number_domain & self.number_domain),
            ~self.number_domain | ~self.number_domain,
        )
        self.assertEqual(
            ~(self.number_domain | self.number_domain),
            ~self.number_domain & ~self.number_domain,
        )

    def test_nary_optimize_sort(self):
        model = self.env["test_orm.mixed"]
        self.assertEqual(
            Domain.AND(
                [
                    Domain("number", "=", 5),
                    Domain("date", "like", "2024"),
                    Domain("date", "!=", False),
                    Domain("number", "<", 99),
                    Domain("comment1", "like", "ok"),
                ]
            ).optimize(model),
            Domain.AND(
                [
                    Domain("comment1", "like", "ok"),
                    Domain("date", "not in", OrderedSet([False])),
                    Domain("date", "like", "2024"),
                    Domain("number", "in", OrderedSet([5])),
                    Domain("number", "<", 99),
                ]
            ),
            "Optimization sorts by field and operator",
        )

    def test_nary_optimize_in(self):
        model = self.env["test_orm.mixed"]

        def domain(op, values):
            if not values:
                return Domain.FALSE if op == "in" else Domain.TRUE
            return Domain("number", op, values)

        set123 = OrderedSet([1, 2, 3])
        set345 = OrderedSet([3, 4, 5])
        set910 = OrderedSet([9, 10])
        sets = [set123, set345, set910, OrderedSet()]
        for a, b in list(combinations(sets, 2)) + list(combinations(reversed(sets), 2)):
            self.assertEqual(
                (domain("in", a) | domain("in", b)).optimize(model),
                domain("in", a | b),
                f"in: {a} | {b}",
            )
            self.assertEqual(
                (domain("in", a) & domain("in", b)).optimize(model),
                domain("in", a & b),
                f"in: {a} & {b}",
            )
            self.assertEqual(
                (domain("not in", a) | domain("not in", b)).optimize(model),
                domain("not in", a & b),
                f"not in {a} | not in {b}",
            )
            self.assertEqual(
                (domain("not in", a) & domain("not in", b)).optimize(model),
                domain("not in", a | b),
                f"not in {a} & not in {b}",
            )
            self.assertEqual(
                (domain("in", a) | domain("not in", b)).optimize(model),
                domain("not in", b - a),
                f"in {a} | not in {b}",
            )
            self.assertEqual(
                (domain("in", a) & domain("not in", b)).optimize(model),
                domain("in", a - b),
                f"in {a} & not in {b}",
            )

        self.assertEqual(
            (
                domain("in", set123) | domain("not in", set910) | domain("in", set345)
            ).optimize(model),
            domain("not in", set910),
        )
        self.assertEqual(
            (
                domain("in", set123) & domain("not in", set345) & domain("in", [1])
            ).optimize(model),
            domain("in", OrderedSet([1])),
        )

        self.assertEqual(
            (~(domain("in", set123) | domain("in", set345))).optimize(model),
            domain("not in", set123 | set345),
        )
        self.assertEqual(
            (~(domain("in", set123) & domain("in", set345))).optimize(model),
            domain("not in", set123 & set345),
        )

        self.assertIsInstance(
            (Domain("number", "in", [1]) | Domain("number", "in", [2]))
            .optimize(model)
            .value,
            OrderedSet,
            "Check we can optimize something else than OrderedSet",
        )

    def test_nary_optimize_in_relational(self):
        model = self.env["test_orm.discussion"]

        with self.subTest(field_type="many2one"):
            d1 = Domain("moderator", "in", [1]).optimize(model)
            d2 = Domain("moderator", "in", [1, 2]).optimize(model)
            self.assertEqual((d1 & d2).optimize(model), d1)
            self.assertEqual((d1 | d2).optimize(model), d2)
            self.assertEqual((~d1 & ~d2).optimize(model), ~d2)
            self.assertEqual((~d1 | ~d2).optimize(model), ~d1)

        with self.subTest(field_type="one2many"):
            d1 = Domain("messages", "in", [1]).optimize(model)
            d2 = Domain("messages", "in", [1, 2]).optimize(model)
            self.assertEqual((d1 & d2).optimize(model), (d1 & d2))
            self.assertEqual((d1 | d2).optimize(model), d2)
            self.assertEqual((~d1 & ~d2).optimize(model), ~d2)
            self.assertEqual((~d1 | ~d2).optimize(model), ~d1 | ~d2)

        with self.subTest(field_type="many2many"):
            d1 = Domain("categories", "in", [1]).optimize(model)
            d2 = Domain("categories", "in", [1, 2]).optimize(model)
            self.assertEqual((d1 & d2).optimize(model), (d1 & d2))
            self.assertEqual((d1 | d2).optimize(model), d2)
            self.assertEqual((~d1 & ~d2).optimize(model), ~d2)
            self.assertEqual((~d1 | ~d2).optimize(model), ~d1 | ~d2)

    def test_nary_optimize_any(self):
        model = self.env["test_orm.discussion"]

        for field_name, left, right in [
            ("moderator", Domain("id", ">", 5), Domain("login", "like", "one")),
            (
                "categories",
                Domain("id", ">", 5),
                Domain("name", "like", "these"),
            ),
            ("messages", Domain("id", ">", 5), Domain("name", "like", "hello")),
        ]:
            field_type = model._fields[field_name].type
            m2o = field_type == "many2one"
            left = left.optimize(model[field_name])
            right = right.optimize(model[field_name])

            with self.subTest(field_type=field_type):
                self.assertEqual(
                    (
                        Domain(field_name, "any", left)
                        | Domain(field_name, "any", right)
                    ).optimize(model),
                    Domain(field_name, "any", left | right),
                )
                self.assertEqual(
                    (
                        Domain(field_name, "any", left)
                        & Domain(field_name, "any", right)
                    ).optimize(model),
                    (
                        Domain(field_name, "any", left & right)
                        if m2o
                        else Domain(field_name, "any", left)
                        & Domain(field_name, "any", right)
                    ),
                )
                query = model[field_name]._search([])
                self.assertEqual(
                    (
                        Domain(field_name, "any", left)
                        | Domain(field_name, "any", query)
                        | Domain(field_name, "any", right)
                    ).optimize(model),
                    Domain(field_name, "any", left | right)
                    | Domain(field_name, "any!", query),
                    "Don't merge query with domains",
                )
                self.assertEqual(
                    (
                        Domain(field_name, "not any", left)
                        | Domain(field_name, "not any", right)
                    ).optimize(model),
                    (
                        Domain(field_name, "not any", left & right)
                        if m2o
                        else Domain(field_name, "not any", left)
                        | Domain(field_name, "not any", right)
                    ),
                )
                self.assertEqual(
                    (
                        Domain(field_name, "not any", left)
                        & Domain(field_name, "not any", right)
                    ).optimize(model),
                    Domain(field_name, "not any", left | right),
                )

                self.assertEqual(
                    (
                        Domain(field_name, "any", left)
                        | Domain(field_name, "not any", right)
                    ).optimize(model),
                    (
                        Domain(field_name, "any", left)
                        | Domain(field_name, "not any", right)
                    ),
                    "Do not merge any and not any",
                )

    def test_nary_optimize_same(self):
        model = self.env["test_orm.mixed"]
        self.assertEqual(
            (self.number_domain & self.number_domain).optimize(model),
            self.number_domain,
        )

    def test_optimize_level_by_level(self):
        def search_foo(model, operator, value):
            return [("name", "=", str(tuple(value)))]

        self.patch(self.registry["test_orm.bar"], "_search_foo", search_foo)
        bar = self.env["test_orm.bar"]
        domain = Domain("foo", "=", 4) | Domain("foo", "=", 5)
        domain = domain.optimize_full(bar)
        self.assertEqual(domain, Domain("name", "in", OrderedSet(["(4, 5)"])))

    @users("admin")
    def test_bypass_comodel_id_lookup(self):
        model = self.env["test_orm.mixed"]
        base_domain = Domain("currency_id.id", "=", 2)
        self.assertEqual(
            list(base_domain.optimize_full(model)),
            [("currency_id", "any", [("id", "in", [2])])],
        )
        self.assertEqual(
            list(base_domain.optimize_full(model.sudo())),
            [("currency_id", "in", [2])],
        )

        base_domain = Domain("currency_id.id", "in", [2, False])
        self.assertEqual(
            list(base_domain.optimize_full(model.sudo())),
            [("currency_id", "in", [2])],
        )

        base_domain = Domain("currency_id.id", "not in", [2])
        self.assertEqual(
            list(base_domain.optimize_full(model.sudo())),
            [("currency_id", "not in", [2, False])],
        )

    def test_domain_subdomain_all_operators(self):
        """All subdomain operators (any, any!, not any, not any!) must parse
        their value as a Domain when internal=True.

        This is a contract test: both the single-condition fast path and the
        stack-based parser must handle these identically. A previous bug had
        the fast path missing any!/not any! subdomain parsing because the
        operator set was hardcoded in two places.
        """
        for op in ("any", "any!", "not any", "not any!"):
            with self.subTest(operator=op):
                dom = Domain(
                    [("partner_id", op, [("name", "ilike", "test")])],
                    internal=True,
                )
                conditions = list(dom.iter_conditions())
                self.assertEqual(len(conditions), 1, f"Expected 1 condition for {op}")
                self.assertIsInstance(
                    conditions[0].value,
                    Domain,
                    f"Operator {op!r} value must be parsed as Domain when internal=True",
                )

                dom2 = Domain(
                    [
                        "&",
                        ("partner_id", op, [("name", "=", "x")]),
                        ("active", "=", True),
                    ],
                    internal=True,
                )
                conditions2 = list(dom2.iter_conditions())
                any_conds = [c for c in conditions2 if c.operator == op]
                self.assertTrue(any_conds, f"Should find condition with operator {op}")
                self.assertIsInstance(
                    any_conds[0].value,
                    Domain,
                    f"Stack parser: operator {op!r} value must be parsed as Domain",
                )


class TestDomainEdgeCases(TransactionCase):
    """Regression tests for ``Domain`` constructor edge cases."""

    def test_domain_empty_list_is_true(self):
        """``Domain([])`` returns the TRUE singleton (well-established)."""
        self.assertIs(Domain([]), Domain.TRUE)

    def test_domain_empty_tuple_is_true(self):
        """``Domain(())`` returns TRUE — symmetric with the list form.

        Regression: previously ``arg == []`` only matched lists, leaving
        ``Domain(())`` to fall through to the parser and crash with
        "malformed domain" on the empty-stack pop.
        """
        self.assertIs(Domain(()), Domain.TRUE)

    def test_custom_domain_in_nary_is_representable(self):
        """``repr()``/``list()`` of an n-ary domain containing a
        ``Domain.custom(...)`` must not raise.

        Regression: ``DomainCustom.__iter__`` used to ``raise
        NotImplementedError``, so ``DomainNary.__iter__`` (which does
        ``yield from child``) crashed whenever a custom-SQL domain was logged or
        interpolated into an error message — and ``cond & Domain.custom(...)``
        is built in purchase/mrp/sale_renting.
        """
        custom = Domain.custom(to_sql=lambda model, alias, query: SQL("TRUE"))
        combined = Domain("id", ">", 0) & custom
        self.assertEqual(
            [type(c).__name__ for c in combined.children][1], "DomainCustom"
        )
        self.assertIsInstance(list(combined), list)
        self.assertIn("custom", repr(combined))

    def test_value_to_datetime_empty_collection(self):
        """``_value_to_datetime`` must return ``(empty, True)`` on empty input,
        not raise ``ValueError`` from unpacking ``zip(*())``.

        Currently mitigated upstream by ``_optimize_in_set`` short-circuiting
        empty ``in``/``not in`` to TRUE/FALSE, but the helper itself must be
        safe so future direct callers do not regress.
        """
        from odoo.orm.domain.optimizations import _value_to_datetime

        value, is_date = _value_to_datetime([], env=self.env, iso_only=False)
        self.assertEqual(list(value), [])
        self.assertTrue(is_date)
        value, is_date = _value_to_datetime((), env=self.env, iso_only=False)
        self.assertEqual(list(value), [])
        self.assertTrue(is_date)

    def test_deep_any_chain_rejected_at_parse(self):
        """A deep ``any`` chain must raise ``ValueError`` at parse time, not a
        ``RecursionError`` later in ``_optimize``/``_to_sql``.

        Regression: the nesting guard only walked the built ``&``/``|``/``!``
        AST, and the single-condition fast path skipped it entirely, so a
        self-referential ``parent_id any (parent_id any (...))`` chain (which a
        client can build over a single field) nested past
        ``MAX_DOMAIN_NESTING`` and blew the stack when evaluated.
        """
        from odoo.orm.domain.ast import MAX_DOMAIN_NESTING

        def nested_any(n, op="any"):
            inner = [("a", "=", 1)]
            for _ in range(n):
                inner = [("parent_id", op, inner)]
            return inner

        Domain(nested_any(5))
        Domain([("partner_id", "any", [("active", "=", True)])])
        with self.assertRaises(ValueError):
            Domain(nested_any(MAX_DOMAIN_NESTING + 5))
        with self.assertRaises(ValueError):
            Domain(nested_any(500, op="not any"))
        with self.assertRaises(ValueError):
            Domain("parent_id", "any", nested_any(500))
        with self.assertRaises(ValueError):
            Domain(nested_any(500), internal=True)
        Domain([("id", "in", list(range(10000)))])


class TestInequalityAgainstNull(TransactionCase):
    """``field <op> False`` on a field with no ``falsy_value`` is an empty domain.

    Regression: ``('id', '>', False)`` used to reach SQL as a *bool* parameter
    bound to an ``int4`` column, because ``Id.convert_to_column`` is an identity
    passthrough and the inequality branch of ``Field._condition_to_sql`` only
    normalized the value when the field defined a ``falsy_value``.  Postgres
    raised ``UndefinedFunction: operator does not exist: integer > boolean``,
    which aborts the whole transaction — and every model has ``id``.

    Fields that *do* define a falsy sentinel (Char ``""``, Integer ``0``, Float
    ``0.0``) compare against it and are deliberately unaffected.
    """

    def test_id_inequality_against_false_is_empty(self):
        """All four inequality operators collapse, for False and for None."""
        model = self.env["res.partner"]
        for operator in (">", ">=", "<", "<="):
            for value in (False, None):
                with self.subTest(operator=operator, value=value):
                    self.assertIs(
                        Domain("id", operator, value).optimize(model),
                        Domain.FALSE,
                    )

    def test_id_inequality_against_false_searches(self):
        """It must not raise at the SQL level, and must match nothing."""
        model = self.env["res.partner"]
        self.assertTrue(model.search_count([]), "need at least one partner")
        for operator in (">", ">=", "<", "<="):
            with self.subTest(operator=operator):
                self.assertEqual(model.search_count([("id", operator, False)]), 0)

    def test_search_and_filtered_domain_agree(self):
        """The SQL path and the Python predicate path must not disagree.

        Collapsing at optimization time (rather than in ``condition_to_sql`` and
        ``filter_function`` separately) is what keeps negation consistent:
        ``~Domain.FALSE`` is TRUE in both paths, whereas SQL's three-valued
        ``NOT (id > NULL)`` excludes every row while Python's ``not False``
        admits every row.
        """
        model = self.env["res.partner"]
        records = model.search([], limit=20)
        self.assertTrue(records)
        for domain in (
            [("id", ">", False)],
            ["!", ("id", ">", False)],
            ["|", ("id", "<", False), ("id", ">=", False)],
            ["!", ("id", "<=", False)],
        ):
            with self.subTest(domain=domain):
                by_sql = model.search([("id", "in", records.ids), *domain])
                by_python = records.filtered_domain(domain)
                self.assertEqual(set(by_sql.ids), set(by_python.ids))

    def test_falsy_value_fields_are_unaffected(self):
        """Fields with a falsy sentinel keep comparing against it."""
        model = self.env["res.partner"]
        self.assertNotEqual(Domain("name", ">", False).optimize(model), Domain.FALSE)
        self.assertNotEqual(Domain("color", ">=", False).optimize(model), Domain.FALSE)


class TestIdComparandValidation(TransactionCase):
    """``Id.convert_to_column`` validates the comparand instead of the database.

    ``id`` was the only field class whose ``convert_to_column`` was an identity
    passthrough, so an ill-typed domain comparand reached psycopg and raised a
    *database* error -- which aborts the transaction, so even a caller that
    catches it loses every subsequent query.  Every sibling field class already
    raised a clean Python error instead; this brings ``id`` in line.
    """

    BAD_VALUES = ("abc", b"x", [], {}, True)

    def test_bad_comparand_raises_cleanly(self):
        model = self.env["res.partner"]
        for value in self.BAD_VALUES:
            with self.subTest(value=value), self.assertRaises(ValueError):
                model.search([("id", ">", value)])

    def test_transaction_survives_a_bad_comparand(self):
        """The point of the fix: the error must not poison the cursor."""
        model = self.env["res.partner"]
        with self.assertRaises(ValueError):
            model.search([("id", ">", "abc")])
        self.assertTrue(self.env["res.country"].search_count([]) >= 0)

    def test_valid_comparands_still_work(self):
        model = self.env["res.partner"]
        records = model.search([], limit=3)
        self.assertTrue(records)
        lowest = min(records.ids)
        self.assertEqual(
            model.search_count([("id", ">=", str(lowest))]),
            model.search_count([("id", ">=", lowest)]),
        )
        self.assertEqual(
            set(model.search([("id", ">=", lowest + 0.5)]).ids),
            set(model.search([("id", ">", lowest)]).ids),
        )

    def test_non_int_id_model_is_untouched(self):
        """An ``_auto = False`` model may key on any column type.

        ``test_orm.view.str.id`` is a ``_table_query`` view whose ``id`` column
        is *text*, so the int validation must not apply to it.
        """
        model = self.env["test_orm.view.str.id"]
        self.assertFalse(model._auto)
        self.assertEqual(model.search([("name", "=", "test")]).id, "hello")
        self.assertEqual(model.search_count([("id", "=", "hello")]), 1)
        self.assertEqual(model.search_count([("id", ">", "a")]), 1)

    def test_ordinary_id_inequalities_still_work(self):
        """The collapse must be scoped to falsy comparands only."""
        model = self.env["res.partner"]
        records = model.search([], limit=5)
        self.assertTrue(records)
        lowest = min(records.ids)
        self.assertEqual(
            set(model.search([("id", "in", records.ids), ("id", ">=", lowest)]).ids),
            set(records.ids),
        )


class TestSearchFilteredDomainParity(TransactionCase):
    """``search()`` and ``filtered_domain()`` must agree on the same domain.

    The two consume the same ``Domain`` but travel entirely separate backends:
    ``search()`` goes ``_optimize(FULL) -> Field.condition_to_sql -> Postgres``,
    ``filtered_domain()`` goes ``_optimize(...) -> Field.filter_function ->
    Python``.  The operator semantics are implemented twice, by hand, and are
    kept in sync only by convention -- so a gap in one shows up as a silent
    disagreement rather than a failure.  ``('id', '>', False)`` lived exactly in
    that seam (see :class:`TestInequalityAgainstNull`).

    This walks a fixed, seeded set of generated domains over both paths.  The
    seed is pinned so the test is deterministic; widen ``ITERATIONS`` locally to
    fuzz harder.
    """

    ITERATIONS = 300
    SEED = 20260724

    CHAR_FIELDS = ("name", "ref", "city", "email", "phone", "street", "function")
    NUM_FIELDS = ("color", "id")
    BOOL_FIELDS = ("active", "is_company")
    M2O_FIELDS = ("country_id", "parent_id", "company_id")
    SEL_FIELDS = ("type",)

    def setUp(self):
        super().setUp()
        fields = self.env["res.partner"]._fields
        for attr in (
            "CHAR_FIELDS",
            "NUM_FIELDS",
            "BOOL_FIELDS",
            "M2O_FIELDS",
            "SEL_FIELDS",
        ):
            present = tuple(name for name in getattr(self, attr) if name in fields)
            self.assertTrue(present, f"no usable field left in {attr}")
            setattr(self, attr, present)

    def _seed_records(self):
        import random

        rng = random.Random(self.SEED)
        countries = self.env["res.country"].search([], limit=5).ids
        candidates = {
            "name": lambda: rng.choice(["", "Alpha", "beta", "Gamma Ltd", "délta"]),
            "city": lambda: rng.choice([False, "", "Paris", "london", "Ávila"]),
            "email": lambda: rng.choice([False, "", "a@b.com", "X@Y.COM"]),
            "phone": lambda: rng.choice([False, "", "+33 1"]),
            "street": lambda: rng.choice([False, "", "1 rue A", "_under"]),
            "function": lambda: rng.choice([False, "", "CEO"]),
            "color": lambda: rng.choice([0, 1, 2, 7]),
            "active": lambda: rng.choice([True, True, False]),
            "is_company": lambda: rng.choice([True, False]),
            "country_id": lambda: rng.choice([False, *countries]),
            "type": lambda: rng.choice(["contact", "invoice", "delivery", "other"]),
        }
        model_fields = self.env["res.partner"]._fields
        usable = {n: f for n, f in candidates.items() if n in model_fields}
        vals = [
            {"ref": f"PARITY{i:04d}", **{n: make() for n, make in usable.items()}}
            for i in range(60)
        ]
        return self.env["res.partner"].create(vals)

    def _rand_leaf(self, rng):
        kind = rng.choice(["char", "num", "bool", "m2o", "sel"])
        if kind == "char":
            operator = rng.choice(
                ["=", "!=", "like", "not like", "ilike", "not ilike", "=like", "in"]
            )
            field = rng.choice(self.CHAR_FIELDS)
            if operator == "in":
                return (field, operator, rng.sample(["Alpha", "beta", "", False], 2))
            return (
                field,
                operator,
                rng.choice(["a", "Alpha", "%a%", "", False, "_lpha"]),
            )
        if kind == "num":
            operator = rng.choice(["=", "!=", "<", ">", "<=", ">=", "in", "not in"])
            field = rng.choice(self.NUM_FIELDS)
            if operator in ("in", "not in"):
                return (field, operator, rng.sample([0, 1, 2, 7, 999], 2))
            return (field, operator, rng.choice([0, 1, 2, 7, False]))
        if kind == "bool":
            return (
                rng.choice(self.BOOL_FIELDS),
                rng.choice(["=", "!="]),
                rng.choice([True, False]),
            )
        if kind == "m2o":
            operator = rng.choice(["=", "!=", "in", "not in", "ilike"])
            field = rng.choice(self.M2O_FIELDS)
            if operator == "ilike":
                return (field, operator, rng.choice(["a", "Fr"]))
            if operator in ("in", "not in"):
                return (field, operator, rng.sample([1, 2, 3, False], 2))
            return (field, operator, rng.choice([False, 1, 2]))
        operator = rng.choice(["=", "!=", "in", "not in"])
        field = rng.choice(self.SEL_FIELDS)
        if operator in ("in", "not in"):
            return (field, operator, ["contact", "invoice"])
        return (field, operator, rng.choice(["contact", "invoice", "delivery"]))

    def _rand_domain(self, rng, depth=0):
        if depth < 2 and rng.random() < 0.45:
            operator = rng.choice(["&", "|", "!"])
            if operator == "!":
                return ["!", *self._rand_domain(rng, depth + 1)]
            return [
                operator,
                *self._rand_domain(rng, depth + 1),
                *self._rand_domain(rng, depth + 1),
            ]
        return [self._rand_leaf(rng)]

    def test_search_matches_filtered_domain(self):
        import random

        records = self._seed_records()
        self.env.flush_all()
        model = self.env["res.partner"].with_context(active_test=False)
        scope = [("id", "in", records.ids)]
        rng = random.Random(self.SEED)
        for _ in range(self.ITERATIONS):
            domain = self._rand_domain(rng)
            with self.subTest(domain=domain):
                by_sql = model.search(scope + domain)
                by_python = records.filtered_domain(domain)
                self.assertEqual(
                    set(by_sql.ids),
                    set(by_python.ids),
                    f"search() and filtered_domain() disagree on {domain}",
                )


class TestDomainConfluence(TransactionCase):
    """Lock in the two invariants ``Domain._optimize`` relies on for correctness.

    ``odoo/orm/domain/ast.py`` documents (in ``_optimize`` and
    ``_optimize_nary_sort_key``) that the optimizer's fixed-point loop is sound
    because the passes are *confluent* and *idempotent*:

    * **idempotence** — optimizing an already-optimized domain is a no-op
      (``optimize(optimize(d)) == optimize(d)``); without this the fixed-point
      loop could oscillate; and
    * **confluence** — domains that differ only in the *order* of their
      conjuncts/disjuncts must optimize to the *same* canonical form. Value-merge
      passes rely on ``_optimize_nary_sort_key`` co-locating mergeable pairs, and
      duplicate-removal is order-independent (a first-occurrence set de-dup), so
      a permutation of the leaves can never produce a different query. A sort-key
      regression, or a return to adjacent-only de-dup, would silently produce
      different (and potentially wrong) queries depending on how the caller
      happened to order the leaves.

    These properties were previously only asserted by a non-existent
    ``tests/models/test_domain_confluence.py`` referenced in ``ast.py``; this
    class is the real backing test.
    """

    def _leaves(self):
        return [
            Domain("count", ">", 5),
            Domain("count", "<", 100),
            Domain("count", "!=", 7),
            Domain("foo", "=", "abc"),
            Domain("currency_id", "in", [1, 2]),
        ]

    def test_optimize_is_idempotent(self):
        model = self.env["test_orm.mixed"]
        for combine in (Domain.AND, Domain.OR):
            once = combine(self._leaves()).optimize(model)
            twice = once.optimize(model)
            self.assertEqual(
                once, twice, f"{combine.__name__} optimize must be idempotent"
            )

    def test_optimize_confluent_under_permutation(self):
        model = self.env["test_orm.mixed"]
        leaves = self._leaves()
        for combine in (Domain.AND, Domain.OR):
            canonical = combine(leaves).optimize(model)
            for perm in permutations(leaves):
                self.assertEqual(
                    combine(list(perm)).optimize(model),
                    canonical,
                    f"{combine.__name__} optimization must be order-independent",
                )

    def test_optimize_dedups_nonadjacent_duplicates(self):
        """Duplicate conditions are removed regardless of position.

        Regression for the adjacent-only de-dup: an operator without a
        value-merge pass (``like``) duplicated across a same-sort-key sibling
        survived in some permutations but not others, so the same logical domain
        optimized to two different SQL strings (different query-cache keys). The
        multiset ``{x, x, y}`` must collapse to ``{x, y}`` for *every* ordering.
        """
        model = self.env["test_orm.mixed"]
        dx = Domain("foo", "like", "x%")
        dy = Domain("foo", "like", "y%")
        leaves = [dx, dy, dx]
        canonical = Domain.OR(leaves).optimize(model)
        self.assertEqual(len(list(canonical.children)), 2)
        for perm in permutations(leaves):
            self.assertEqual(
                Domain.OR(list(perm)).optimize(model),
                canonical,
                "duplicate conditions must be removed order-independently",
            )


class TestDomainAgainstRawRows(TransactionCase):
    """Evaluate domains against the raw table, outside the ORM entirely.

    Every other domain test compares two ORM paths -- ``search()`` against
    ``filtered_domain()``. That is blind to the optimizer: both consume the SAME
    optimized domain, so a bad rewrite in ``odoo/orm/domain/optimizations.py``
    changes both sides identically and the comparison stays green. (Measured:
    swapping ``child_of`` with ``parent_of`` produces zero differences between
    the two paths.)

    Here the expectation comes from a plain ``SELECT`` plus a Python evaluator,
    so a rewrite that changes meaning has nowhere to hide. Injecting two
    optimizer bugs -- ``'='`` building a ``not in`` set, and ``'=like'`` gaining
    implicit wildcards -- makes this fail, which is what the differential could
    not do.

    The evaluator mirrors the IN/NOT-IN construction in
    ``Field._condition_to_sql`` (not the optimizer above it), including the
    ``falsy_value`` aliasing that makes ``= False`` match both NULL and ``""``.
    If that construction is ever changed deliberately, this test must be updated
    with it -- on purpose: it is the record of what the SQL is supposed to mean.
    """

    COLUMNS = {
        "name": "",
        "ref": "",
        "city": "",
        "email": "",
        "function": "",
        "color": 0,
        "active": False,
        "is_company": False,
        "id": None,
    }

    def setUp(self):
        super().setUp()
        import random

        rng = random.Random(4242)
        self.records = self.env["res.partner"].create(
            [
                {
                    "name": rng.choice(["", "Alpha", "beta", "Gamma", "délta"]),
                    "ref": f"RAW{i:03d}",
                    "city": rng.choice([False, "", "Paris", "london"]),
                    "email": rng.choice([False, "", "a@b.com", "X@Y.COM"]),
                    "function": rng.choice([False, "", "CEO"]),
                    "color": rng.choice([0, 1, 2, 7]),
                    "active": rng.choice([True, True, False]),
                    "is_company": rng.choice([True, False]),
                }
                for i in range(40)
            ]
        )
        self.env.flush_all()
        self.Partner = self.env["res.partner"].with_context(active_test=False)
        cols = ", ".join(f'"{c}"' for c in self.COLUMNS if c != "id")
        self.env.cr.execute(
            f"SELECT id, {cols} FROM res_partner WHERE id = ANY(%s)",
            (self.records.ids,),
        )
        self.rows = {r["id"]: r for r in self.env.cr.dictfetchall()}

    def _eval_in(self, column, operator, values, raw):
        """Mirror Field._condition_to_sql's IN / NOT IN construction."""
        falsy = self.COLUMNS[column]
        params = [v for v in values if v is not False and v is not None]
        null_in = len(params) < len(values)
        if falsy is not None:
            if falsy in params:
                null_in = True
            elif null_in:
                params = [*params, falsy]

        if not params:
            expr = False
        elif operator == "in":
            expr = raw is not None and raw in params
        else:
            expr = raw is not None and raw not in params

        if (operator == "in") == null_in:
            return expr or raw is None
        if operator == "not in" and null_in and not params:
            return raw is not None
        return expr

    def _expected(self, leaf):
        column, operator, value = leaf
        if operator in ("=", "!="):
            operator, value = ("in" if operator == "=" else "not in"), [value]
        return {
            rid
            for rid, row in self.rows.items()
            if self._eval_in(column, operator, list(value), row[column])
        }

    def test_equality_matches_the_raw_rows(self):
        leaves = [
            ("name", "=", "Alpha"),
            ("name", "!=", "Alpha"),
            ("name", "=", False),
            ("name", "!=", False),
            ("city", "=", False),
            ("city", "!=", False),
            ("city", "=", "Paris"),
            ("email", "!=", "a@b.com"),
            ("function", "=", False),
            ("color", "=", 0),
            ("color", "!=", 0),
            ("color", "=", 7),
            ("active", "=", True),
            ("active", "=", False),
            ("active", "!=", False),
            ("is_company", "!=", True),
        ]
        sizes = set()
        for leaf in leaves:
            with self.subTest(leaf=leaf):
                expected = self._expected(leaf)
                found = self.Partner.search([("id", "in", self.records.ids), leaf])
                self.assertEqual(set(found.ids), expected)
                sizes.add(len(expected))
        self.assertGreater(
            len({s for s in sizes if 0 < s < len(self.records)}),
            1,
            "leaves must discriminate: expected sets are all empty or all-inclusive",
        )

    def test_set_membership_matches_the_raw_rows(self):
        leaves = [
            ("name", "in", ["Alpha", "beta"]),
            ("name", "not in", ["Alpha", "beta"]),
            ("name", "in", ["Alpha", False]),
            ("name", "not in", ["Alpha", False]),
            ("city", "in", [False]),
            ("city", "not in", [False]),
            ("color", "in", [0, 7]),
            ("color", "not in", [0, 7]),
            ("color", "in", [2, False]),
            ("color", "not in", [1, 2]),
            ("email", "in", ["a@b.com", ""]),
        ]
        sizes = set()
        for leaf in leaves:
            with self.subTest(leaf=leaf):
                expected = self._expected(leaf)
                found = self.Partner.search([("id", "in", self.records.ids), leaf])
                self.assertEqual(set(found.ids), expected)
                sizes.add(len(expected))
        self.assertGreater(
            len({s for s in sizes if 0 < s < len(self.records)}),
            1,
            "leaves must discriminate: expected sets are all empty or all-inclusive",
        )

    def test_falsy_value_aliasing_is_not_lost(self):
        """``= False`` must match BOTH NULL and the column's falsy value.

        The rows deliberately contain city NULL and city '' -- SQL aliases them,
        Python set algebra does not, and the optimizer's set merges rely on the
        aliasing being applied before they run.
        """
        cities = {row["city"] for row in self.rows.values()}
        self.assertIn(None, cities, "fixture must contain a NULL city")
        self.assertIn("", cities, "fixture must contain an empty-string city")

        found = self.Partner.search(
            [("id", "in", self.records.ids), ("city", "=", False)]
        )
        expected = {rid for rid, row in self.rows.items() if row["city"] in (None, "")}
        self.assertEqual(set(found.ids), expected)
        self.assertTrue(expected)
