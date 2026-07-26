"""A domain must mean the same thing to both of its evaluators.

The ORM evaluates every domain twice, through two independent implementations:

* ``search()`` → ``Domain._to_sql`` → ``Field.condition_to_sql`` (PostgreSQL),
* ``filtered_domain()`` → ``Domain._as_predicate`` → ``Field.filter_function``
  (in-memory Python).

Nothing in the type system ties the two together, and they are reached at
*different* optimization levels (``_to_sql`` requires FULL, ``_as_predicate``
stops at DYNAMIC_VALUES), so they drift silently.  Drift is not cosmetic: the
Python evaluator backs ``ir.rule`` checks on unsaved records and onchange domain
evaluation, so a record can pass the in-memory check and fail the SQL one.

These tests pin the three drifts a differential sweep over
``(field, operator, value)`` triples surfaced, plus a general parity sweep so
the next one fails here instead of in production.

:class:`TestDomainEvaluatorParityGenerated` adds a seeded generator on top:
hand-written cases only cover shapes someone thought of, and all three drifts
above were combinations of an ordinary field with an ordinary comparand. The
generator draws from the same value pool that produced them -- string
comparands, fractional comparands on integer columns, falsy values -- and
composes them with and/or/not.
"""

import random

from odoo.exceptions import UserError
from odoo.orm.domain import Domain
from odoo.tests.common import TransactionCase


class TestDomainEvaluatorParity(TransactionCase):
    """``search(domain)`` and ``filtered_domain(domain)`` must agree."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.records = cls.Partner.create(
            [
                {"name": "P-null"},
                {"name": "P-empty", "comment": "", "ref": "", "color": 0},
                {
                    "name": "P-note",
                    "comment": "note",
                    "ref": "R1",
                    "color": 3,
                    "type": "invoice",
                    "partner_latitude": 10.5,
                },
                {
                    "name": "P-abc",
                    "comment": "abc",
                    "ref": "r2",
                    "color": 5,
                    "employee": True,
                    "partner_latitude": 0.0,
                },
            ]
        )
        cls.env.flush_all()

    def assertParity(self, domain, msg=""):
        """Assert both evaluators select the same records for ``domain``."""
        scoped = [("id", "in", self.records.ids), *domain]
        sql_ids = set(self.Partner.with_context(active_test=False).search(scoped).ids)
        py_ids = set(self.records.filtered_domain(domain).ids)
        self.assertEqual(
            sql_ids,
            py_ids,
            f"search() and filtered_domain() disagree on {domain!r} {msg}",
        )
        return sql_ids

    def test_inequality_string_comparand_on_integer_field(self):
        """``('int_field', '>', '3')`` — a string comparand, the ordinary shape
        produced by the web client and stored in ``ir.filters``.

        ``condition_to_sql`` coerced it through ``convert_to_cache`` while
        ``filter_function`` compared the raw string, so building the Python
        predicate died with ``TypeError: '>' not supported between instances of
        'int' and 'str'`` on a domain ``search()`` handled fine.
        """
        for operator in (">", ">=", "<", "<="):
            with self.subTest(operator=operator):
                self.assertParity([("color", operator, "3")])
        self.assertEqual(
            self.assertParity([("color", ">", "3")]),
            self.assertParity([("color", ">", 3)]),
            "a string comparand must select the same rows as its int form",
        )

    def test_inequality_comparand_on_html_field(self):
        """Html stores sanitized markup (``note`` → ``<p>note</p>``).

        SQL compared the *sanitized* comparand (what is actually in the column)
        while Python compared the raw one, so the two returned different sets.
        Both must now use the same, converted comparand.
        """
        for operator in (">", ">=", "<", "<="):
            with self.subTest(operator=operator):
                self.assertParity([("comment", operator, "note")])
        self.assertEqual(
            self.assertParity([("comment", ">=", "note")]),
            {self.records[2].id},
        )

    def test_inequality_on_relational_field_rejects_non_id(self):
        """A relational inequality against anything but a single id is refused.

        ``('parent_id', '>', [1, 2])`` used to reach PostgreSQL as
        ``integer > smallint[]`` and abort the transaction with a raw
        ``UndefinedFunction`` — from a domain any authenticated RPC caller can
        send — while ``filtered_domain`` silently returned nothing.
        """
        for value in ([1, 2], ["a"], True, "5", self.records[:1]):
            for operator in (">", ">=", "<", "<="):
                with self.subTest(value=value, operator=operator):
                    domain = [("parent_id", operator, value)]
                    with self.assertRaises(TypeError):
                        self.Partner.search(domain)
                    with self.assertRaises(TypeError):
                        self.records.filtered_domain(domain)

    def test_inequality_on_relational_field_accepts_numbers(self):
        """Numeric comparands keep working — the rejection above is a deny list.

        ``int`` and ``float`` were measured to produce valid SQL before the fix
        (PostgreSQL promotes ``int4`` for the comparison), so narrowing the rule
        to a deny list is what keeps them working; an allow list of "int only"
        silently broke ``('parent_id', '>', 2.5)``.
        """
        pivot = self.records[1].id
        for value in (pivot, float(pivot)):
            for operator in (">", ">=", "<", "<="):
                with self.subTest(value=value, operator=operator):
                    self.assertParity([("parent_id", operator, value)])

    def test_parity_sweep(self):
        """Differential sweep: every (field, operator, value) triple must either
        select the same records on both sides, or fail on both sides.
        """
        values = {
            "ref": ["R1", "", False, None, "r", 3],
            "color": [0, 3, "3", False, None, 2.0],
            "comment": ["note", "", False, None],
            "name": ["P-note", "", False, None, "P", 7],
            "active": [True, False, None],
            "employee": [True, False, None],
            "type": ["contact", "other", False, None],
            "partner_latitude": [0.0, 10.5, "10.5", False, None],
            "create_date": ["2020-01-15 00:00:00", False, None],
            "parent_id": [False, None],
        }
        operators = [
            "=", "!=", "in", "not in",
            "like", "not like", "ilike", "not ilike", "=like",
            ">", "<", ">=", "<=",
        ]  # fmt: skip
        for fname, vals in values.items():
            for operator in operators:
                for value in vals:
                    domain = [(fname, operator, value)]
                    with self.subTest(domain=domain):
                        self._assert_same_outcome(domain)
                    if operator in ("in", "not in"):
                        domain = [(fname, operator, [value])]
                        with self.subTest(domain=domain):
                            self._assert_same_outcome(domain)

    def test_null_alias_inside_in_collection(self):
        """Every spelling of "no value" inside an in/not-in set means NULL.

        ``Field._condition_to_sql`` counts both ``False`` and ``None`` as null
        markers, and additionally aliases a field's ``falsy_value`` (``""`` for
        char/text, ``0`` for integer, ``0.0`` for float) with NULL.  The Python
        evaluator's ``Field.filter_function`` tested only ``False`` and
        ``falsy_value`` — so ``('ref', 'in', [None])`` made ``search()`` return
        the NULL rows while ``filtered_domain()`` returned nothing, on every
        field type.  ``_optimize_in_set_falsy_value`` now canonicalizes all of
        them to ``False`` before either evaluator sees the node.
        """
        cases = {
            "ref": [[None], [""], [False]],
            "comment": [[None], [""], [False]],
            "color": [[None], [0], [False]],
            "partner_latitude": [[None], [0.0], [False]],
            "type": [[None], [False]],
            "parent_id": [[None], [False]],
        }
        for fname, collections in cases.items():
            baseline_in = baseline_not_in = None
            for collection in collections:
                for operator in ("in", "not in"):
                    domain = [(fname, operator, collection)]
                    with self.subTest(domain=domain):
                        self.assertParity(domain)
                        scoped = [("id", "in", self.records.ids), *domain]
                        got = set(
                            self.Partner.with_context(active_test=False)
                            .search(scoped)
                            .ids
                        )
                        if operator == "in":
                            if baseline_in is None:
                                baseline_in = got
                            self.assertEqual(
                                got,
                                baseline_in,
                                f"{fname}: {collection!r} disagrees with the "
                                f"other null spellings",
                            )
                        else:
                            if baseline_not_in is None:
                                baseline_not_in = got
                            self.assertEqual(got, baseline_not_in)
            self.assertEqual(baseline_in | baseline_not_in, set(self.records.ids))
            self.assertFalse(baseline_in & baseline_not_in)

    def _assert_same_outcome(self, domain):
        """Both evaluators must succeed with equal results, or both must fail."""
        scoped = [("id", "in", self.records.ids), *domain]
        sql_error = py_error = None
        try:
            with self.env.cr.savepoint():
                sql_ids = set(
                    self.Partner.with_context(active_test=False).search(scoped).ids
                )
        except (TypeError, ValueError, UserError) as exc:
            sql_error = exc
        try:
            py_ids = set(self.records.filtered_domain(domain).ids)
        except (TypeError, ValueError, UserError) as exc:
            py_error = exc

        if sql_error is not None or py_error is not None:
            self.assertEqual(
                sql_error is not None,
                py_error is not None,
                f"only one evaluator rejected {domain!r}: "
                f"sql={sql_error!r} python={py_error!r}",
            )
            return
        self.assertEqual(sql_ids, py_ids, f"evaluators disagree on {domain!r}")


class TestDomainComparandExactness(TransactionCase):
    """A domain comparand must be compared **exactly**.

    Parity alone cannot catch this class of bug: both evaluators share
    ``Field._inequality_comparand``, so a *lossy* coercion of the comparand makes
    them agree on the same wrong answer.  Every assertion below therefore checks
    the selected records against what is actually stored, on top of parity.

    The comparand used to be pushed through the field's **storage** conversion
    (``convert_to_column`` / ``convert_to_cache``), which is allowed to lose
    information because the column cannot hold more: ``Integer`` truncates
    (``int(2.5) == 2``) and ``Float(digits=...)`` rounds
    (``float_round(0.01000004, 6) == 0.01``).  Applied to a *threshold* that
    moved the comparison boundary, and since the Python evaluator does not apply
    it to equality, the two evaluators disagreed there.
    """

    def assertSelects(self, model, records, domain, expected, msg=""):
        """Assert both evaluators select exactly ``expected`` for ``domain``."""
        scoped = [("id", "in", records.ids), *domain]
        sql = model.with_context(active_test=False).search(scoped)
        python = records.filtered_domain(domain)
        self.assertEqual(
            set(sql.ids),
            set(python.ids),
            f"search() and filtered_domain() disagree on {domain!r} {msg}",
        )
        self.assertEqual(
            set(sql.ids),
            set(expected.ids),
            f"wrong records for {domain!r} {msg}",
        )

    def test_integer_fractional_comparand(self):
        """A fractional comparand on an integer column.

        ``('number', '<', 2.5)`` used to be truncated to ``< 2`` (in *both*
        evaluators) and lose every record with ``number == 2``; ``'>=' 2.5``
        wrongly kept them; ``'=' 2.5`` matched ``number == 2`` under ``search()``
        and nothing under ``filtered_domain()``.  PostgreSQL compares ``int4``
        against a fractional number exactly, so nothing needs truncating.
        """
        Model = self.env["test_orm.empty_int"]
        one, two, three, null = Model.create(
            [{"number": 1}, {"number": 2}, {"number": 3}, {}]
        )
        self.env.flush_all()
        records = one + two + three + null
        self.assertSelects(Model, records, [("number", "<", 2.5)], one + two + null)
        self.assertSelects(Model, records, [("number", "<=", 2.5)], one + two + null)
        self.assertSelects(Model, records, [("number", ">", 2.5)], three)
        self.assertSelects(Model, records, [("number", ">=", 2.5)], three)
        self.assertSelects(Model, records, [("number", "=", 2.5)], Model)
        self.assertSelects(Model, records, [("number", "!=", 2.5)], records)
        self.assertSelects(Model, records, [("number", "in", [2.5, 3])], three)
        self.assertSelects(Model, records, [("number", "not in", [2.5])], records)
        self.assertSelects(Model, records, [("number", ">=", -0.5)], records)

    def test_integer_string_comparand(self):
        """String comparands on an integer column.

        ``'2'`` must behave like ``2``; ``'2.5'`` like ``2.5`` (it used to reach
        ``int('2.5')`` inside ``convert_to_column`` and raise a bare
        ``ValueError`` — a 500 on any user-supplied domain — while
        ``filtered_domain`` quietly matched nothing); a value that is not a
        number at all matches nothing for equality (instead of raising in one
        evaluator only) and is rejected in both for an ordering comparison.
        """
        Model = self.env["test_orm.empty_int"]
        one, two, three = Model.create([{"number": 1}, {"number": 2}, {"number": 3}])
        self.env.flush_all()
        records = one + two + three
        self.assertSelects(Model, records, [("number", "=", "2")], two)
        self.assertSelects(Model, records, [("number", "<", "2.5")], one + two)
        self.assertSelects(Model, records, [("number", "=", "2.5")], Model)
        self.assertSelects(Model, records, [("number", "=", "abc")], Model)
        self.assertSelects(Model, records, [("number", "!=", "abc")], records)
        for operator in (">", ">=", "<", "<="):
            with self.subTest(operator=operator):
                domain = [("number", operator, "abc")]
                with self.assertRaises(ValueError):
                    Model.search(domain)
                with self.assertRaises(ValueError):
                    records.filtered_domain(domain)

    def test_float_digits_comparand(self):
        """A comparand finer than the column's ``digits``.

        ``('float_2', '<', 10.004)`` used to round the *threshold* to ``10.00``
        and drop every row equal to ``10.00``; ``'=' 10.004`` matched all of them
        under ``search()`` (rounded) and none under ``filtered_domain()`` (raw).
        """
        Model = self.env["decimal.precision.test"]
        low, mid, high = Model.create(
            [{"float_2": 9.99}, {"float_2": 10.00}, {"float_2": 10.01}]
        )
        self.env.flush_all()
        records = low + mid + high
        self.assertSelects(Model, records, [("float_2", "<", 10.004)], low + mid)
        self.assertSelects(Model, records, [("float_2", "<=", 10.004)], low + mid)
        self.assertSelects(Model, records, [("float_2", ">", 10.004)], high)
        self.assertSelects(Model, records, [("float_2", ">=", 10.004)], high)
        self.assertSelects(Model, records, [("float_2", "=", 10.004)], Model)
        self.assertSelects(Model, records, [("float_2", "!=", 10.004)], records)
        self.assertSelects(Model, records, [("float_2", ">", 9.996)], mid + high)
        self.assertSelects(Model, records, [("float_2", "=", 10.00)], mid)


class TestDomainWildcardOnlyPattern(TransactionCase):
    """``like``/``ilike`` against a pattern made only of wildcards.

    ``%`` matches every string, empty one included, so the condition is a
    tautology — but SQL's three-valued ``LIKE`` never matches a NULL row while
    the Python predicate reads an unset value as ``""`` and matches it.  So
    ``('name', 'ilike', '%')`` returned every record under ``filtered_domain()``
    and *none* under ``search()``, and ``not ilike '%'`` the exact opposite.
    The ORM aliases NULL with the field's falsy value everywhere else (see
    ``_optimize_in_set_falsy_value``), which is the reading kept here.
    """

    def test_wildcard_only_pattern_on_char(self):
        Model = self.env["test_orm.empty_char"]
        null, empty, abc = Model.create([{}, {"name": ""}, {"name": "abc"}])
        self.env.flush_all()
        records = null + empty + abc
        for pattern in ("%", "%%"):
            for operator in ("like", "ilike", "=like", "=ilike"):
                with self.subTest(operator=operator, pattern=pattern):
                    domain = [("name", operator, pattern)]
                    self.assertEqual(
                        set(Model.search([("id", "in", records.ids), *domain]).ids),
                        set(records.ids),
                        f"{domain!r} must match every record",
                    )
                    self.assertEqual(
                        set(records.filtered_domain(domain).ids), set(records.ids)
                    )
                negative = [("name", f"not {operator}", pattern)]
                self.assertFalse(
                    Model.search([("id", "in", records.ids), *negative]),
                    f"{negative!r} must match no record",
                )
                self.assertFalse(records.filtered_domain(negative))
        for domain, expected in (
            ([("name", "ilike", "_")], abc),
            ([("name", "=ilike", "_")], Model),
        ):
            self.assertEqual(
                set(Model.search([("id", "in", records.ids), *domain]).ids),
                set(expected.ids),
            )
            self.assertEqual(
                set(records.filtered_domain(domain).ids), set(expected.ids)
            )

    def test_wildcard_only_pattern_on_many2one(self):
        """On a relational field the name-search reading applies: a corecord
        whose display name matches "anything" exists iff the relation is set.
        """
        Model = self.env["test_orm.team"]
        parent = Model.create({"name": "root"})
        with_parent = Model.create({"name": "child", "parent_id": parent.id})
        self.env.flush_all()
        records = parent + with_parent
        for domain, expected in (
            ([("parent_id", "ilike", "%")], with_parent),
            ([("parent_id", "not ilike", "%")], parent),
        ):
            self.assertEqual(
                set(Model.search([("id", "in", records.ids), *domain]).ids),
                set(expected.ids),
                f"wrong records for {domain!r}",
            )
            self.assertEqual(
                set(records.filtered_domain(domain).ids),
                set(expected.ids),
                f"filtered_domain disagrees on {domain!r}",
            )


class TestDomainIdComparand(TransactionCase):
    """String comparands on ``id``, alone and merged with a sibling condition.

    ``id`` is the one numeric field the optimizer deliberately does *not*
    canonicalize (``_optimize_numeric_comparand`` skips it: every prefetch
    optimizes ``('id', 'in', ids)`` and scanning those collections was measured
    at +46% on ``optimize_full``).  Everything that follows from that exception is
    pinned here.
    """

    def setUp(self):
        super().setUp()
        self.Model = self.env["test_orm.empty_int"]
        self.records = self.Model.create([{"number": n} for n in (1, 2, 3, 4)])
        self.env.flush_all()

    def assertParity(self, domain, expected):
        scoped = [("id", "in", self.records.ids), *domain]
        sql = set(self.Model.with_context(active_test=False).search(scoped).ids)
        python = set(self.records.filtered_domain(domain).ids)
        self.assertEqual(sql, python, f"evaluators disagree on {domain!r}")
        self.assertEqual(sql, set(expected.ids), f"wrong records for {domain!r}")

    def test_string_id_comparand(self):
        """``('id', <op>, '3')`` must select what the int form selects.

        The Python evaluator compared the raw string (``3 in {'3'}``, and
        ``3 >= '3'`` raising a ``TypeError`` that ``check_inequality`` swallows),
        so it matched nothing where ``search()`` matched.
        """
        second = self.records[1]
        self.assertParity([("id", "=", str(second.id))], second)
        self.assertParity([("id", "in", [str(second.id)])], second)
        self.assertParity([("id", "!=", str(second.id))], self.records - second)
        self.assertParity([("id", ">=", str(second.id))], self.records[1:])
        self.assertParity([("id", "<", str(second.id))], self.records[0])

    def test_string_id_merged_with_sibling_condition(self):
        """A string id must survive the n-ary set merge.

        The merge combines value sets by element identity, so ``{1, 2, 3, 4} &
        {'2'}`` was empty and the whole domain collapsed to FALSE in SQL — while
        each condition alone selected record 2 in both evaluators.
        """
        first, second = self.records[0], self.records[1]
        self.assertParity(
            [("id", "in", [str(second.id), first.id]), ("id", "in", self.records.ids)],
            first + second,
        )
        self.assertParity(
            [("id", "not in", [str(second.id)]), ("id", "in", self.records.ids)],
            self.records - second,
        )
        self.assertParity([("number", "in", ["2"]), ("number", "in", [2, 3])], second)

    def test_non_id_string_comparand(self):
        """A value that is not an id matches nothing — in both evaluators.

        Equality drops it (the SQL merge concludes the same); an ordering
        comparison has no answer and raises on both sides.
        """
        self.assertParity([("id", "in", ["abc"])], self.Model)
        self.assertParity(
            [("id", "in", ["abc"]), ("id", "in", self.records.ids)], self.Model
        )
        for operator in (">", ">=", "<", "<="):
            with self.subTest(operator=operator):
                domain = [("id", operator, "abc")]
                with self.assertRaises(ValueError):
                    self.Model.search(domain)
                with self.assertRaises(ValueError):
                    self.records.filtered_domain(domain)

    def test_fractional_id_comparand(self):
        """``id`` accepts a fractional bound, as a string too.

        A float comparand was always accepted (``id >= 2.5`` means ``id >= 3``),
        but its string spelling raised ``ValueError`` from ``int('2.5')`` — in
        both evaluators, yet inconsistently with every other numeric field once
        comparands are canonicalized.
        """
        second, third = self.records[1], self.records[2]
        for value in (float(third.id) - 0.5, str(float(third.id) - 0.5)):
            with self.subTest(value=value):
                self.assertParity([("id", ">=", value)], self.records[2:])
                self.assertParity([("id", "<", value)], self.records[:2])
                self.assertParity([("id", "=", value)], self.Model)
        self.assertParity([("id", ">", str(float(second.id)))], self.records[2:])

    def test_text_id_model_is_left_alone(self):
        """A model that keys ``id`` on a text column keeps string ids working.

        ``test_orm.view.str.id`` is a ``_table_query`` view whose id is
        ``'hello'``; coercing ids to int there would break it, so both the
        optimizer's merge canonicalization and ``Id.filter_function`` must pass
        the value through (``convert_to_column`` already does, via ``_auto``).
        """
        View = self.env["test_orm.view.str.id"]
        rows = View.search([])
        self.assertEqual(rows.ids, ["hello"])
        for domain in (
            [("id", "=", "hello")],
            [("id", "in", ["hello"])],
            [("id", "in", ["hello"]), ("id", "in", ["hello", "other"])],
            [("id", ">", "a")],
        ):
            with self.subTest(domain=domain):
                self.assertEqual(View.search(domain).ids, ["hello"])
                self.assertEqual(rows.filtered_domain(domain).ids, ["hello"])


class TestDomainEvaluatorParityGenerated(TransactionCase):
    """Seeded generative parity sweep.

    Deterministic: a fixed seed and its own fixture, so a failure reproduces
    exactly and reports the offending domain.
    """

    SEED = 20260726
    DOMAINS = 400

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.records = cls.Partner.create(
            [
                {"name": "G-null"},
                {"name": "G-empty", "comment": "", "ref": "", "color": 0},
                {"name": "G-zero", "color": 0, "partner_latitude": 0.0, "ref": "0"},
                {"name": "G-neg", "color": -3, "partner_latitude": -1.5, "ref": "-1"},
                {"name": "G-one", "color": 1, "partner_latitude": 1.0, "ref": "1"},
                {"name": "G-two", "color": 2, "partner_latitude": 2.5, "ref": "2"},
                {"name": "G-three", "color": 3, "partner_latitude": 3.0, "ref": "R3"},
                {"name": "G-ten", "color": 10, "partner_latitude": 10.5, "ref": "r10"},
                {"name": "G-type", "color": 5, "type": "invoice", "employee": True},
                {"name": "G-dup", "color": 5, "ref": "R3", "comment": "note"},
                {"name": "G-uni", "color": 7, "ref": "Ünïcøde", "comment": "nöte"},
                {"name": "G-pct", "color": 8, "ref": "50%_off", "comment": "a_b%c"},
            ]
        )
        cls.env.flush_all()

    def _specs(self):
        num_ops = ["=", "!=", "<", "<=", ">", ">="]
        text_ops = [
            "=",
            "!=",
            "in",
            "not in",
            "like",
            "not like",
            "ilike",
            "=like",
            *num_ops,
        ]
        return [
            (
                "color",
                num_ops + ["in", "not in"],
                [0, 1, 2, 3, -3, 2.5, -1.5, "2", "0", False],
            ),
            ("partner_latitude", num_ops, [0.0, 1.0, 2.5, -1.5, 3, "1", False]),
            ("ref", text_ops, ["R3", "r10", "", "0", "%", "_", "Ünïcøde", False, 3]),
            ("comment", text_ops, ["note", "nöte", "a_b%c", "", False]),
            ("name", text_ops, ["G-one", "g-", "%", "", False]),
            ("type", ["=", "!=", "in", "not in"], ["invoice", "contact", "", False]),
            ("employee", ["=", "!=", "in", "not in"], [True, False]),
            ("active", ["=", "!=", "in", "not in"], [True, False]),
        ]

    def _condition(self, rng, specs):
        fname, ops, values = rng.choice(specs)
        op = rng.choice(ops)
        if op in ("in", "not in"):
            value = rng.sample(values, rng.randint(1, min(3, len(values))))
        else:
            value = rng.choice(values)
        return Domain(fname, op, value)

    def _domain(self, rng, specs, depth=0):
        if depth >= 2 or rng.random() < 0.5:
            return self._condition(rng, specs)
        parts = [self._domain(rng, specs, depth + 1) for _ in range(rng.randint(2, 3))]
        roll = rng.random()
        if roll < 0.4:
            return Domain.AND(parts)
        if roll < 0.8:
            return Domain.OR(parts)
        return ~parts[0]

    def _evaluate(self, model, records, domain):
        """Return ``(error_name, ids)`` for one evaluator, never raising.

        A domain the ORM refuses is a legitimate outcome; what must not differ
        is *which* evaluator refuses it.
        """
        with self.env.cr.savepoint(flush=False):
            try:
                if model is not None:
                    scoped = Domain("id", "in", records.ids) & domain
                    return None, set(model.search(scoped).ids)
                return None, set(records.filtered_domain(domain).ids)
            except Exception as error:
                return type(error).__name__, None

    def test_generated_domains_agree_between_evaluators(self):
        """Both evaluators accept and select the same records, or both refuse."""
        rng = random.Random(self.SEED)
        specs = self._specs()
        records = self.records.with_context(active_test=False)
        model = self.Partner.with_context(active_test=False)
        refused = 0
        for index in range(self.DOMAINS):
            domain = self._domain(rng, specs)
            with self.subTest(index=index, domain=list(domain)):
                sql_error, sql_ids = self._evaluate(model, records, domain)
                py_error, py_ids = self._evaluate(None, records, domain)
                context = f"on {list(domain)!r} (seed={self.SEED}, index={index})"
                self.assertEqual(
                    sql_error is None,
                    py_error is None,
                    f"one evaluator refused and the other did not {context}: "
                    f"search={sql_error or 'ok'} filtered_domain={py_error or 'ok'}",
                )
                if sql_error is None:
                    self.assertEqual(sql_ids, py_ids, f"evaluators disagree {context}")
                else:
                    refused += 1
        self.assertLess(
            refused,
            self.DOMAINS // 2,
            "most generated domains were refused — the generator stopped "
            "exercising the evaluators",
        )
