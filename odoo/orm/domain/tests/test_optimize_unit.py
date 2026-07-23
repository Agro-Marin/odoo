"""Pure-Python regression tests for the domain optimizer — no Odoo, no database.

``Domain.optimize(model)`` / ``optimize_full(model)`` only read ``model._name``
and ``model._fields[name].{type, relational, comodel_name, ...}``, so the whole
optimizer (``optimizations.py``, ~1k lines of rewrite passes) is exercisable
against a ten-line stub model — milliseconds per case, no registry bootstrap.
The full-stack suite (``addons/test_orm/tests/test_domain.py``) uses a real
``TransactionCase``; this suite locks the BASIC-level algebra so a confluence or
canonicalisation regression fails here, fast, instead of as a slow search in
production.

Every expected value below was captured from the live optimizer, not assumed.
"""

import unittest
from datetime import date, datetime
from unittest.mock import patch

from odoo.libs.datetime import utc

# Importing registers all optimization passes onto ``_OPTIMIZATIONS_FOR``.
# Required because the stubbed ``odoo.orm.domain.__init__`` never runs (it is the
# real package's ``__init__`` that normally pulls ``optimizations`` in).
from odoo.orm.domain import optimizations
from odoo.orm.domain.ast import (
    MAX_DOMAIN_NESTING,
    Domain,
    DomainCondition,
    OptimizationLevel,
)
from odoo.tools import OrderedSet

_UNSET = object()  # sentinel: "falsy_value not passed" vs. explicit None


class _StubField:
    """Minimal structural stand-in for :class:`odoo.fields.Field`.

    Carries only the attributes the optimizer reads when resolving a leaf.
    """

    # Falsy value SQL-aliases with NULL/False per field type, matching the real
    # Field subclasses (textual="", numeric=0/0.0, boolean=False, else None).
    _FALSY_BY_TYPE = {
        "char": "",
        "text": "",
        "html": "",
        "integer": 0,
        "float": 0.0,
        "monetary": 0.0,
        "boolean": False,
    }

    def __init__(
        self,
        name,
        ftype="integer",
        *,
        relational=False,
        comodel=None,
        search=None,
        falsy_value=_UNSET,
    ):
        self.name = name
        self.type = ftype
        self.relational = relational
        self.model_name = "m"
        self.comodel_name = comodel
        self.store = True
        self.required = False
        self.inherited = False
        self.company_dependent = False
        # Real fields carry ``falsy_value`` (class default ``None``); the
        # optimizer reads it to canonicalize falsy elements in in/not-in sets.
        self.falsy_value = (
            self._FALSY_BY_TYPE.get(ftype) if falsy_value is _UNSET else falsy_value
        )
        # A field's search method (truthy → the FULL optimizer routes leaves on
        # this field through ``determine_domain`` instead of a raw column).
        self.search = search


class _StubEnv:
    """Environment stand-in for the two attributes the optimizer reads:
    ``env.tz`` (date -> naive-UTC datetime conversion) and ``env[comodel]``
    (descending into ``any`` sub-domains)."""

    tz = utc  # == the optimizer's ``utc``: dates convert to naive midnight

    def __init__(self, model):
        self._model = model

    def __getitem__(self, model_name):
        return self._model


class _StubModel:
    """Ten-line stand-in for a recordset: just ``_name`` and ``_fields``."""

    _name = "m"

    def __init__(self):
        self._fields = {
            "a": _StubField("a"),
            "b": _StubField("b"),
            "c": _StubField("c"),
            "name": _StubField("name", "char"),
            "ok": _StubField("ok", "boolean"),
            "d": _StubField("d", "date"),
            "dt": _StubField("dt", "datetime"),
            "rel": _StubField("rel", "many2one", relational=True, comodel="m"),
        }
        self.env = _StubEnv(self)


def _opt(domain):
    """Optimise ``domain`` against the stub model and return the legacy list form."""
    return list(domain.optimize(_StubModel()))


class TestScalarNormalisation(unittest.TestCase):
    """Scalar (in)equality leaves canonicalise to ``in`` / ``not in`` sets."""

    def test_eq_becomes_in(self):
        self.assertEqual(_opt(Domain("a", "=", 1)), [("a", "in", [1])])

    def test_neq_becomes_not_in(self):
        self.assertEqual(_opt(Domain("a", "!=", 1)), [("a", "not in", [1])])

    def test_in_singleton_stays_in(self):
        self.assertEqual(_opt(Domain("a", "in", [1])), [("a", "in", [1])])

    def test_in_dedups_values(self):
        self.assertEqual(_opt(Domain("a", "in", [1, 2, 2, 1])), [("a", "in", [1, 2])])

    def test_like_is_left_alone(self):
        self.assertEqual(_opt(Domain("name", "like", "x")), [("name", "like", "x")])


class TestBooleanNormalisation(unittest.TestCase):
    """Boolean leaves normalise to ``in [True]`` regardless of phrasing."""

    def test_eq_true(self):
        self.assertEqual(_opt(Domain("ok", "=", True)), [("ok", "in", [True])])

    def test_neq_false_equals_eq_true(self):
        self.assertEqual(_opt(Domain("ok", "!=", False)), [("ok", "in", [True])])


class TestNegation(unittest.TestCase):
    """``~`` folds into the leaf operator; double negation cancels."""

    def test_single_negation(self):
        self.assertEqual(_opt(~Domain("a", "=", 1)), [("a", "not in", [1])])

    def test_double_negation_cancels(self):
        self.assertEqual(_opt(~~Domain("a", "=", 1)), [("a", "in", [1])])


class TestSetMerging(unittest.TestCase):
    """Same-field conditions merge by set algebra (union / intersection)."""

    def test_or_unions(self):
        self.assertEqual(
            _opt(Domain("a", "in", [1, 2]) | Domain("a", "in", [2, 3])),
            [("a", "in", [1, 2, 3])],
        )

    def test_and_intersects(self):
        self.assertEqual(
            _opt(Domain("a", "in", [1, 2]) & Domain("a", "in", [2, 3])),
            [("a", "in", [2])],
        )

    def test_or_of_eqs_merges(self):
        self.assertEqual(
            _opt(Domain("a", "=", 1) | Domain("a", "=", 2)),
            [("a", "in", [1, 2])],
        )

    def test_and_of_equal_eqs_dedups(self):
        self.assertEqual(
            _opt(Domain("a", "=", 1) & Domain("a", "=", 1)),
            [("a", "in", [1])],
        )

    def test_contradiction_collapses_to_false(self):
        # a == 1 AND a == 2 is unsatisfiable; (0, '=', 1) is the FALSE leaf.
        self.assertEqual(
            _opt(Domain("a", "=", 1) & Domain("a", "=", 2)),
            [(0, "=", 1)],
        )

    def test_distinct_field_inequalities_not_merged(self):
        # Range merging is not a BASIC pass: two ``<`` on one field are kept.
        # They ARE canonically ordered by value, though, so the optimized form
        # (and its SQL/query-cache key) is independent of the caller's leaf order.
        canonical = ["&", ("a", "<", 3), ("a", "<", 5)]
        self.assertEqual(_opt(Domain("a", "<", 5) & Domain("a", "<", 3)), canonical)
        self.assertEqual(_opt(Domain("a", "<", 3) & Domain("a", "<", 5)), canonical)


class TestFalsyValueSetMerging(unittest.TestCase):
    """A field's ``falsy_value`` (``""`` for char) is SQL-aliased with False/NULL.

    The optimizer must canonicalize it to ``False`` in in/not-in sets so the
    n-ary set-merge (which uses Python set algebra, where ``"" != False``) stays
    sound. Regression guard for the previously-wrong collapses.
    """

    def test_eq_empty_string_canonicalizes_to_false(self):
        # ``name = ""`` and ``name = False`` are the same SQL predicate.
        self.assertEqual(_opt(Domain("name", "=", "")), [("name", "in", [False])])
        self.assertEqual(_opt(Domain("name", "=", False)), [("name", "in", [False])])

    def test_neq_empty_string_canonicalizes_to_false(self):
        self.assertEqual(_opt(Domain("name", "!=", "")), [("name", "not in", [False])])
        self.assertEqual(
            _opt(Domain("name", "!=", False)), [("name", "not in", [False])]
        )

    def test_or_of_neq_empty_and_neq_false_is_not_tautology(self):
        # BUG GUARD: both mean "non-empty", so the union is "not in [False]",
        # NOT the TRUE domain that plain set algebra ("" != False) produced.
        self.assertEqual(
            _opt(Domain("name", "!=", "") | Domain("name", "!=", False)),
            [("name", "not in", [False])],
        )

    def test_and_of_eq_empty_and_neq_false_is_false(self):
        # "is falsy" AND "is not falsy" is a contradiction → FALSE leaf.
        self.assertEqual(
            _opt(Domain("name", "=", "") & Domain("name", "!=", False)),
            [(0, "=", 1)],
        )

    def test_in_set_mixed_empty_and_value(self):
        self.assertEqual(
            _opt(Domain("name", "in", ["a", ""])), [("name", "in", ["a", False])]
        )
        self.assertEqual(
            _opt(Domain("name", "in", ["a", False])), [("name", "in", ["a", False])]
        )


class TestBooleanAbsorption(unittest.TestCase):
    """TRUE / FALSE absorb correctly in AND / OR."""

    def test_true_and_x_is_x(self):
        self.assertEqual(_opt(Domain.TRUE & Domain("a", "=", 1)), [("a", "in", [1])])

    def test_false_and_x_is_false(self):
        self.assertEqual(_opt(Domain.FALSE & Domain("a", "=", 1)), [(0, "=", 1)])

    def test_true_or_x_is_true(self):
        self.assertEqual(_opt(Domain.TRUE | Domain("a", "=", 1)), [(1, "=", 1)])

    def test_false_or_x_is_x(self):
        self.assertEqual(_opt(Domain.FALSE | Domain("a", "=", 1)), [("a", "in", [1])])


class TestNaryFlattening(unittest.TestCase):
    """Nested same-operator n-ary nodes flatten into one node."""

    def test_nested_and_flattens(self):
        d = (Domain("a", "=", 1) & Domain("b", "=", 2)) & Domain("c", "=", 3)
        self.assertEqual(
            _opt(d),
            ["&", "&", ("a", "in", [1]), ("b", "in", [2]), ("c", "in", [3])],
        )

    def test_nested_or_flattens(self):
        d = (Domain("a", "=", 1) | Domain("b", "=", 2)) | Domain("c", "=", 3)
        self.assertEqual(
            _opt(d),
            ["|", "|", ("a", "in", [1]), ("b", "in", [2]), ("c", "in", [3])],
        )


class TestOptimizerInvariants(unittest.TestCase):
    """Cross-cutting guarantees the rest of the ORM relies on."""

    def test_optimize_does_not_mutate_original(self):
        # Reusing an UN-optimised domain across models must stay safe, so
        # optimize() returns a new tree and leaves the input at level NONE.
        original = Domain("a", "=", 1)
        original.optimize(_StubModel())
        self.assertEqual(list(original), [("a", "=", 1)])
        self.assertIs(original._opt_level, OptimizationLevel.NONE)

    def test_optimize_state_is_written_atomically(self):
        # The (level, model_name) pair lives in ONE slot so a threaded reader
        # never observes a torn ``(FULL, None)`` node -- which would read as
        # "model-independent" and skip a different model's BASIC value coercion,
        # emitting wrong SQL. A pass-through leaf caches its level in place (a
        # tested contract); this pins that the stamp is a single tuple.
        original = Domain("name", "like", "x")
        self.assertEqual(original._opt, (OptimizationLevel.NONE, None))
        out = original.optimize(_StubModel())
        self.assertIs(out, original)
        self.assertEqual(out._opt, (OptimizationLevel.BASIC, "m"))

    def test_optimize_is_idempotent(self):
        model = _StubModel()
        once = (Domain("a", "in", [1, 2]) | Domain("a", "in", [2, 3])).optimize(model)
        twice = once.optimize(model)
        self.assertEqual(once, twice)
        self.assertIs(once._opt_level, twice._opt_level)

    def test_boolean_singletons_optimize_to_themselves(self):
        model = _StubModel()
        self.assertIs(Domain.TRUE.optimize(model), Domain.TRUE)
        self.assertIs(Domain.FALSE.optimize(model), Domain.FALSE)


class TestOptimizeModelScoping(unittest.TestCase):
    """``_opt_level`` is cached per model: reusing an optimised (canonical)
    domain against a different model must not skip type-dependent BASIC
    coercion, which would silently emit wrong SQL.
    """

    class _Field:
        def __init__(self, name, ftype, model_name):
            self.name = name
            self.type = ftype
            self.relational = False
            self.model_name = model_name
            self.comodel_name = None
            self.store = True
            self.required = False
            self.inherited = False
            self.company_dependent = False
            self.falsy_value = _StubField._FALSY_BY_TYPE.get(ftype)

    class _Model:
        def __init__(self, name, field_types):
            self._name = name
            self._fields = {
                n: TestOptimizeModelScoping._Field(n, t, name)
                for n, t in field_types.items()
            }

    def test_reuse_across_models_recoerces_value(self):
        int_model = self._Model("int_model", {"a": "integer"})
        bool_model = self._Model("bool_model", {"a": "boolean"})
        # optimise against a model where `a` is integer (value stays an int)
        opt = Domain("a", "=", 5).optimize(int_model)
        self.assertEqual(list(opt), [("a", "in", [5])])
        # reuse the SAME canonical, level-stamped node against a model where
        # `a` is boolean: it must re-coerce (5 -> True), not return the stale int.
        reused = list(opt.optimize(bool_model))
        self.assertEqual(reused, list(Domain("a", "=", 5).optimize(bool_model)))
        self.assertEqual(reused, [("a", "in", [True])])

    def test_same_model_reuse_stays_idempotent(self):
        int_model = self._Model("int_model", {"a": "integer"})
        opt = Domain("a", "=", 5).optimize(int_model)
        again = opt.optimize(int_model)
        self.assertEqual(list(again), list(opt))
        self.assertIs(again._opt_level, opt._opt_level)
        self.assertEqual(opt._opt_model_name, "int_model")

    def test_reuse_across_models_leaves_shared_node_unmutated(self):
        # The cross-model ``_opt`` race: optimizing a node canonical for one
        # model against another must NOT reset/restamp the shared node in place.
        # Otherwise a concurrent optimizer for the first model observes the torn
        # cache and skips a level ("Trying to skip optimization level") or skips
        # type coercion (wrong SQL).  The second model's optimize works on a
        # private copy; the shared node keeps its original stamp.
        int_model = self._Model("int_model", {"a": "integer"})
        bool_model = self._Model("bool_model", {"a": "boolean"})
        node = Domain("a", "=", 5).optimize(int_model)
        stamp_before = node._opt
        self.assertEqual(node._opt_model_name, "int_model")

        reused = node.optimize(bool_model)  # different model → private copy
        self.assertEqual(list(reused), [("a", "in", [True])])  # coerced for bool
        self.assertIsNot(reused, node)
        # The shared node's stamp is untouched by the other-model optimize.
        self.assertEqual(node._opt, stamp_before)
        self.assertEqual(node._opt_model_name, "int_model")
        # ...and it still cache-hits for its own model (returns itself, no work).
        self.assertIs(node.optimize(int_model), node)


if __name__ == "__main__":
    unittest.main()


class TestBooleanSearchableTautology(unittest.TestCase):
    """`searchable_bool in [True, False]` must collapse to TRUE before the
    field's search method is invoked (upstream 7a67274e138)."""

    def _model_with_searchable_bool(self, calls):
        model = _StubModel()
        field = _StubField("flag", "boolean", search=True)

        def determine_domain(model, operator, value):
            calls.append((operator, sorted(value)))
            return [("a", "in", [1])]

        field.determine_domain = determine_domain
        model._fields["flag"] = field
        return model

    def test_in_true_false_collapses_before_search(self):
        calls = []
        model = self._model_with_searchable_bool(calls)
        result = Domain("flag", "in", [True, False]).optimize_full(model)
        # The tautology collapses to TRUE; the search method must not run.
        self.assertEqual(calls, [])
        self.assertEqual(list(result), [(1, "=", 1)])  # TRUE domain, legacy form

    def test_single_value_still_uses_search(self):
        calls = []
        model = self._model_with_searchable_bool(calls)
        result = Domain("flag", "in", [True]).optimize_full(model)
        # A genuine single-valued query still delegates to the search method.
        self.assertEqual(calls, [("in", [True])])
        self.assertEqual(list(result), [("a", "in", [1])])


class TestDatetimeEqualityGranularity(unittest.TestCase):
    """'=' on a datetime field matches per element granularity: a datetime
    value covers its whole second, a date value covers its whole *day*.

    Regression: the equality rewrite used ``timedelta(seconds=1)``
    unconditionally, so ``dt = date(2024, 1, 1)`` (and ``dt = 'today'`` once
    the DYNAMIC pass resolved it to a date) matched only ``[00:00:00,
    00:00:01)`` — e.g. ``search_count([('create_date', '=', 'today')])``
    returned 0.  The whole-second/whole-day windows mirror the inequality
    granularity so '=', '<' and '>' partition the axis exactly.
    """

    def test_eq_datetime_expands_to_whole_second(self):
        self.assertEqual(
            _opt(Domain("dt", "=", datetime(2024, 1, 1, 10, 30, 15, 123456))),
            [
                "&",
                ("dt", "<", datetime(2024, 1, 1, 10, 30, 16)),
                ("dt", ">=", datetime(2024, 1, 1, 10, 30, 15)),
            ],
        )

    def test_eq_date_expands_to_whole_day(self):
        self.assertEqual(
            _opt(Domain("dt", "=", date(2024, 1, 1))),
            [
                "&",
                ("dt", "<", datetime(2024, 1, 2)),
                ("dt", ">=", datetime(2024, 1, 1)),
            ],
        )

    def test_eq_iso_date_string_expands_to_whole_day(self):
        self.assertEqual(
            _opt(Domain("dt", "=", "2024-01-01")),
            [
                "&",
                ("dt", "<", datetime(2024, 1, 2)),
                ("dt", ">=", datetime(2024, 1, 1)),
            ],
        )

    def test_neq_date_is_whole_day_complement(self):
        # complement of [d, d+1day), plus the NULL branch from negation
        self.assertEqual(
            _opt(Domain("dt", "!=", date(2024, 1, 1))),
            [
                "|",
                "|",
                ("dt", "in", [False]),
                ("dt", "<", datetime(2024, 1, 1)),
                ("dt", ">=", datetime(2024, 1, 2)),
            ],
        )

    def test_in_mixed_date_and_datetime_granularities(self):
        # one whole-day window for the date, one whole-second window for the
        # datetime, in a single 'in' collection
        self.assertEqual(
            _opt(Domain("dt", "in", [date(2024, 1, 1), datetime(2024, 3, 4, 5, 6, 7)])),
            [
                "|",
                "&",
                ("dt", "<", datetime(2024, 1, 2)),
                ("dt", ">=", datetime(2024, 1, 1)),
                "&",
                ("dt", "<", datetime(2024, 3, 4, 5, 6, 8)),
                ("dt", ">=", datetime(2024, 3, 4, 5, 6, 7)),
            ],
        )

    def test_eq_max_date_has_no_upper_bound(self):
        # date.max + 1 day overflows datetime: the window degrades to a
        # one-sided range instead of raising OverflowError
        self.assertEqual(
            _opt(Domain("dt", "=", date(9999, 12, 31))),
            [("dt", ">=", datetime(9999, 12, 31))],
        )

    def test_eq_today_resolves_to_whole_day(self):
        # 'today' stays a string at BASIC (transaction-independent), resolves
        # to a *date* at DYNAMIC (its date-ness is deliberately preserved), and
        # the re-run BASIC pass must then apply whole-day granularity
        with patch.object(
            optimizations, "resolve_date", return_value=date(2024, 1, 5)
        ):
            self.assertEqual(
                list(Domain("dt", "=", "today").optimize_full(_StubModel())),
                [
                    "&",
                    ("dt", "<", datetime(2024, 1, 6)),
                    ("dt", ">=", datetime(2024, 1, 5)),
                ],
            )

    def test_eq_lt_gt_date_partition_the_axis(self):
        # '=' d -> [d, d+1d) must complement '<' d -> < d and '>' d -> >= d+1d:
        # every instant satisfies exactly one of the three
        d = date(2024, 1, 1)
        self.assertEqual(_opt(Domain("dt", "<", d)), [("dt", "<", datetime(2024, 1, 1))])
        self.assertEqual(
            _opt(Domain("dt", ">", d)), [("dt", ">=", datetime(2024, 1, 2))]
        )


class TestRelativePassSkipsWithoutStrings(unittest.TestCase):
    """The DYNAMIC relative-date passes return the *same node* when the value
    set holds nothing to resolve, instead of allocating an identical condition
    on every pass (mirrors ``_optimize_relational_name_search``)."""

    def test_datetime_set_without_strings_is_same_object(self):
        condition = DomainCondition("dt", "in", OrderedSet([datetime(2024, 1, 1)]))
        result = optimizations._optimize_type_datetime_relative(
            condition, _StubModel()
        )
        self.assertIs(result, condition)

    def test_date_set_without_strings_is_same_object(self):
        condition = DomainCondition("d", "in", OrderedSet([date(2024, 1, 1)]))
        result = optimizations._optimize_type_date_relative(condition, _StubModel())
        self.assertIs(result, condition)

    def test_set_with_string_still_resolves(self):
        condition = DomainCondition(
            "dt", "in", OrderedSet(["today", datetime(2024, 3, 4, 5, 6, 7)])
        )
        with patch.object(
            optimizations, "resolve_date", return_value=date(2024, 1, 5)
        ):
            result = optimizations._optimize_type_datetime_relative(
                condition, _StubModel()
            )
        self.assertIsNot(result, condition)
        # the string resolves to its *date* object (date-ness preserved for the
        # BASIC re-run); non-string elements pass through untouched
        self.assertEqual(
            list(result.value), [date(2024, 1, 5), datetime(2024, 3, 4, 5, 6, 7)]
        )


class TestSubdomainNestingGuardCaseInsensitive(unittest.TestCase):
    """The parse-time ``any`` nesting guard must match operators
    case-insensitively, exactly like the parser (which lowercases them later in
    ``DomainCondition.checked``): a raw uppercase "ANY" level used to slip past
    the guard and RecursionError at evaluation time."""

    @staticmethod
    def _nested_any(depth, op):
        subdomain = [("a", "=", 1)]
        for _ in range(depth):
            subdomain = [("rel", op, subdomain)]
        return subdomain

    def _assert_rejected_at_parse(self, op):
        # top level lowercase (no DeprecationWarning); the *inner* raw levels
        # carry the operator under test and are only seen by the guard's scan
        with self.assertRaisesRegex(ValueError, "nesting too deep"):
            Domain("rel", "any", self._nested_any(MAX_DOMAIN_NESTING + 10, op))

    def test_lowercase_any_deep_chain_rejected(self):
        self._assert_rejected_at_parse("any")

    def test_uppercase_any_deep_chain_rejected(self):
        self._assert_rejected_at_parse("ANY")

    def test_uppercase_not_any_deep_chain_rejected(self):
        self._assert_rejected_at_parse("NOT ANY")


class TestDeepDomainSurfacesValueError(unittest.TestCase):
    """Entry points that optimize internally (``validate``, condition
    ``_as_predicate``) must surface a stack-exhausting domain as the same
    catchable ``ValueError`` as ``optimize``/``optimize_full`` — not as an
    opaque ``RecursionError`` (reachable from ir.rule's constraint via
    ``validate`` and from ``filtered_domain`` via ``_as_predicate``)."""

    def test_validate_surfaces_value_error(self):
        # operator-built (&/|) domains never pass through the parse-time
        # nesting guard, so a deep alternating chain reaches _optimize intact
        domain = Domain("a", "=", 1)
        for _ in range(2000):
            domain = (domain & Domain("a", "=", 2)) | Domain("a", "=", 3)
        with self.assertRaisesRegex(ValueError, "nesting too deep"):
            domain.validate(_StubModel())

    def test_as_predicate_surfaces_value_error(self):
        # Domain-valued 'any' conditions skip the raw-list nesting guard in
        # ``checked()``, so a deep chain is constructible and only recurses
        # when optimized — here from the _as_predicate entry point
        domain = Domain("a", "=", 1)
        for _ in range(5000):
            domain = Domain("rel", "any", domain)
        with self.assertRaisesRegex(ValueError, "nesting too deep"):
            domain._as_predicate(_StubModel())


class TestMergedSetCanonicalOrder(unittest.TestCase):
    """Merged in/not-in sets are emitted in canonical element order.

    The element order of the set does not change the flat leaf's SQL (single
    bound parameter), but it leaks into sibling-subtree ordering through the
    repr-based ``_nary_subtree_tiebreak``, making semantically identical
    domains optimize to ``!=`` trees with different SQL text.  Unmerged sets
    keep the caller's order (no churn)."""

    def test_or_union_is_value_sorted(self):
        canonical = [("a", "in", [1, 2, 3])]
        self.assertEqual(_opt(Domain("a", "in", [3, 1]) | Domain("a", "in", [2])), canonical)
        self.assertEqual(_opt(Domain("a", "in", [2]) | Domain("a", "in", [3, 1])), canonical)

    def test_and_intersection_is_value_sorted(self):
        self.assertEqual(
            _opt(Domain("a", "in", [2, 1, 3]) & Domain("a", "in", [3, 1, 2])),
            [("a", "in", [1, 2, 3])],
        )

    def test_and_not_in_union_is_value_sorted(self):
        self.assertEqual(
            _opt(Domain("a", "not in", [5, 4]) & Domain("a", "not in", [6])),
            [("a", "not in", [4, 5, 6])],
        )

    def test_unmerged_set_keeps_caller_order(self):
        # a single (unmerged) set is semantically order-free; leave it alone
        self.assertEqual(_opt(Domain("a", "in", [3, 1])), [("a", "in", [3, 1])])

    def test_confluence_across_sibling_subtrees(self):
        # permutations of the same leaves must optimize to ``==`` Domains with
        # identically-ordered nested sibling subtrees (same SQL text)
        model = _StubModel()

        def sub(values):
            domain = Domain("ok", "=", True)
            for v in values:
                domain |= Domain("a", "in", [v])
            return domain

        other = Domain("b", "in", [7]) | Domain("name", "like", "z")
        d1 = (sub([1, 2]) & other).optimize(model)
        d2 = (other & sub([2, 1])).optimize(model)
        self.assertEqual(d1, d2)
        self.assertEqual(list(d1), list(d2))
