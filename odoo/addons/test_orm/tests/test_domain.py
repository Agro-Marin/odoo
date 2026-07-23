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
        # just overwrite the defaults here, because we test complements manually
        return super()._search(model, domain, init_domain, test_complement)

    def test_00_test_bool_undefined(self):
        """Undefined/empty values in the database equal False and differ from True."""

        # Add a new boolean column after that some rows/tuples has been added (with data)
        # Existing rows/tuples will be undefined/empty
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

        # optimize() turns `in`/`=` values into OrderedSet (formerly unhashable)
        d1 = Domain("number", "in", [1, 2, 3]).optimize(Model)
        d2 = Domain("number", "in", [3, 2, 1]).optimize(Model)  # different order
        self.assertEqual(d1, d2)
        self.assertEqual(hash(d1), hash(d2))  # invariant a == b ⟹ hash == hash
        self.assertEqual(len({d1, d2}), 1)  # usable as set/dict keys

        # a nary domain with set-valued leaves is hashable end-to-end
        nary = Domain.OR(
            [Domain("number", "in", [1, 2]), Domain("number", "=", 5)]
        ).optimize(Model)
        self.assertIsInstance(hash(nary), int)  # must not raise

        # scalar conditions still differentiate by value (hash quality preserved)
        self.assertNotEqual(
            hash(Domain("number", "=", 1).optimize(Model)),
            hash(Domain("number", "=", 2).optimize(Model)),
        )

    def test_empty_int(self):
        EmptyInt = self.env["test_orm.empty_int"]
        records = EmptyInt.create(
            [
                {"number": 42},  # stored as 42
                {"number": 0},  # stored as 0
                {"number": False},  # stored as 0
                {},  # stored as NULL
            ]
        )
        # check read (NULL is returned as 0)
        self.assertListEqual(records.mapped("number"), [42, 0, 0, 0])

        # check database value
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

        # check ('number', 'in', subset) for every subset of {42, 0, False}
        values = [42, 0, False]
        for length in range(len(values) + 1):
            for subset in combinations(values, length):
                self.assertEqual(
                    self._search(EmptyInt, [("number", "in", list(subset))]),
                    records.filtered(lambda record: record.number in subset),
                    f"Incorrect result for search([('number', 'in', {sorted(subset)})])",
                )
                self.assertEqual(
                    self._search(EmptyInt, [("number", "not in", list(subset))]),
                    records.filtered(lambda record: record.number not in subset),
                    f"Incorrect result for search([('number', 'not in', {sorted(subset)})])",
                )

    def test_empty_char(self):
        EmptyChar = self.env["test_orm.empty_char"]
        records = EmptyChar.create(
            [
                {"name": "name"},
                {"name": ""},  # stored as ''
                {"name": False},  # stored as null (explicitly asked)
                {},  # stored as null
            ]
        )
        # check read
        self.assertListEqual(records.mapped("name"), ["name", "", False, False])

        # check database value
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
                # check against a subset containing both values for empty strings
                subset_check = set(subset)
                if {False, ""} & subset_check:
                    subset_check |= {False, ""}
                self.assertEqual(
                    self._search(EmptyChar, [("name", "in", list(subset))]),
                    records.filtered(lambda record: record.name in subset_check),
                    f"Incorrect result for search([('name', 'in', {list(subset)})])",
                )
                self.assertEqual(
                    self._search(EmptyChar, [("name", "not in", list(subset))]),
                    records.filtered(lambda record: record.name not in subset_check),
                    f"Incorrect result for search([('name', 'not in', {list(subset)})])",
                )

        # =like check
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
                # check against a subset containing both values for empty strings
                subset_check = set(subset)
                if {False, ""} & subset_check:
                    subset_check |= {False, ""}
                self.assertEqual(
                    self._search(records_fr, [("name", "in", list(subset))]),
                    records_fr.filtered(lambda record: record.name in subset_check),
                    f"Incorrect result for search([('name', 'in', {list(subset)})])",
                )
                self.assertEqual(
                    self._search(records_fr, [("name", "not in", list(subset))]),
                    records_fr.filtered(lambda record: record.name not in subset_check),
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
        # Link parent_1.child_1 to parent_1.child_2
        parent_1.child_ids[0].link_sibling_id = parent_1.child_ids[1]
        # Link parent_2.child_2 to parent_2.child_1
        parent_2.child_ids[1].link_sibling_id = parent_2.child_ids[0]

        # Check any/not any traversing normal Many2one
        res_search = self._search(
            Child, [("link_sibling_id", "any", [("quantity", ">", 5)])]
        )
        self.assertEqual(res_search, parent_1.child_ids[0])

        res_search = self._search(
            Child, [("link_sibling_id", "not any", [("quantity", ">", 5)])]
        )
        self.assertEqual(res_search, parent_1.child_ids[1] + parent_2.child_ids)

        # Check any/not any traversing bypass_search_access Many2one
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

        # Check any/not any traversing delegate Many2one
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

        # Check any/not any traversing normal one2many
        res_search = self._search(
            Parent, [("child_ids", "any", [("quantity", "=", 1)])]
        )
        self.assertEqual(res_search, parent_1)

        res_search = self._search(
            Parent, [("child_ids", "not any", [("quantity", "=", 1)])]
        )
        self.assertEqual(res_search, parent_2 + parent_3)

        # Check any/not any traversing bypass_search_access Many2one
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
        # bypass_search_access + without
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

        # Check any/not any traversing normal Many2Many
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
        # the terms do not change during the build of the condition
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
            # fields must be validated
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
        # the deprecation warning itself is asserted in the _warn test below;
        # here we only check the rewrite, so silence the expected warning.
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
            # The two AND-ed subtrees are emitted in canonical (content-sorted)
            # order, not in the caller's value order, so the optimized form is
            # independent of how the ``not in`` collection was written: the 2023
            # subtree sorts before the 2024 one.
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

    def test_not_optimize(self):
        # optimizations are tested with nary
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
        # check all possible pairs (a, b) of sets above
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

        # check when the optimizations are applied, the results are checked
        # by the previous test function
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
            # many2one
            ("moderator", Domain("id", ">", 5), Domain("login", "like", "one")),
            # many2many
            (
                "categories",
                Domain("id", ">", 5),
                Domain("name", "like", "these"),
            ),
            # one2many
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
            # groups values to check that it is called once
            return [("name", "=", str(tuple(value)))]

        self.patch(self.registry["test_orm.bar"], "_search_foo", search_foo)
        bar = self.env["test_orm.bar"]
        domain = Domain("foo", "=", 4) | Domain("foo", "=", 5)
        domain = domain.optimize_full(bar)
        self.assertEqual(domain, Domain("name", "in", OrderedSet(["(4, 5)"])))

    @users("admin")  # just so it's not SUPERUSER to be able to de-escalate su.
    def test_bypass_comodel_id_lookup(self):
        model = self.env["test_orm.mixed"]
        base_domain = Domain("currency_id.id", "=", 2)
        self.assertEqual(  # without sudo
            list(base_domain.optimize_full(model)),
            [("currency_id", "any", [("id", "in", [2])])],
        )
        self.assertEqual(  # with sudo
            list(base_domain.optimize_full(model.sudo())),
            [("currency_id", "in", [2])],
        )

        # check how False is managed
        base_domain = Domain("currency_id.id", "in", [2, False])
        self.assertEqual(  # with sudo
            list(base_domain.optimize_full(model.sudo())),
            [("currency_id", "in", [2])],
        )

        base_domain = Domain("currency_id.id", "not in", [2])
        self.assertEqual(  # with sudo
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
                # Single-condition fast path: [("field", op, [subcondition])]
                dom = Domain(
                    [("partner_id", op, [("name", "ilike", "test")])],
                    internal=True,
                )
                # The value should have been parsed as a Domain, not left as list
                conditions = list(dom.iter_conditions())
                self.assertEqual(len(conditions), 1, f"Expected 1 condition for {op}")
                self.assertIsInstance(
                    conditions[0].value,
                    Domain,
                    f"Operator {op!r} value must be parsed as Domain when internal=True",
                )

                # Stack-based parser: ['&', ("field", op, subcond), ("other", "=", 1)]
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
        self.assertEqual([type(c).__name__ for c in combined.children][1], "DomainCustom")
        # both previously raised NotImplementedError
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

        # shallow chains (legitimate use) still build
        Domain(nested_any(5))
        Domain([("partner_id", "any", [("active", "=", True)])])
        # deep chains are rejected up front, via every construction path
        with self.assertRaises(ValueError):
            Domain(nested_any(MAX_DOMAIN_NESTING + 5))
        with self.assertRaises(ValueError):
            Domain(nested_any(500, op="not any"))
        with self.assertRaises(ValueError):
            Domain("parent_id", "any", nested_any(500))
        with self.assertRaises(ValueError):
            Domain(nested_any(500), internal=True)
        # a huge non-subdomain ('in') value must not be mistaken for nesting
        Domain([("id", "in", list(range(10000)))])


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

    # Mix of mergeable same-field conditions (count: a range + an exclusion)
    # and unrelated fields, so the sort key has real reordering work to do.
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
        # the duplicate is actually gone: {x, x, y} -> {x, y}
        self.assertEqual(len(list(canonical.children)), 2)
        for perm in permutations(leaves):
            self.assertEqual(
                Domain.OR(list(perm)).optimize(model),
                canonical,
                "duplicate conditions must be removed order-independently",
            )
