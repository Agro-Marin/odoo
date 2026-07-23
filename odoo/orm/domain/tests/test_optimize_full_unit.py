"""Pure-Python unit tests for the FULL-level domain optimization passes.

Tier-1 suite (stubbed ``odoo.*`` packages, no framework import — run from the
repo root as plain ``pytest``).  ``test_optimize_unit.py`` locks the BASIC
algebra; this suite covers the FULL passes that were untested:

* the eight-case rewrite table of ``_optimize_m2o_bypass_comodel_id_lookup``;
* ``_optimize_any_with_rights`` (su / bypass_search_access gating);
* the remaining ``_optimize_in_required`` gates (id-field, fast path,
  falsy_value) — the strip/fallback/NewId cases live in
  ``test_optimize_unit.TestInRequiredPredicateSafety``;
* the fallback ladder of ``DomainCondition._optimize_field_search_method``
  (direct → inverse-operator retry → ``any!`` sudo fallback → ``=``/``!=``
  expansion → error propagation / final UserError).

Every expected value below was captured from the live optimizer, not assumed.
"""

import types
import unittest

from odoo.exceptions import UserError

# Importing registers all optimization passes onto ``_OPTIMIZATIONS_FOR``
# (the stubbed ``odoo.orm.domain.__init__`` never runs — see conftest).
from odoo.orm.domain import optimizations
from odoo.orm.domain.ast import Domain, DomainCondition
from odoo.tools import OrderedSet


class _StubField:
    """Minimal structural stand-in carrying the attributes the FULL passes read."""

    def __init__(self, name, ftype="integer", *, relational=False, comodel=None):
        self.name = name
        self.type = ftype
        self.relational = relational
        self.model_name = "m"
        self.comodel_name = comodel
        self.store = True
        self.required = False
        self.inherited = False
        self.company_dependent = False
        self.falsy_value = None
        self.search = None
        self.bypass_search_access = False


class _StubEnv:
    su = True

    def __init__(self, model):
        self._model = model

    def __getitem__(self, model_name):
        return self._model


class _StubModel:
    _name = "m"
    _ids = ()

    def __init__(self):
        self._fields = {
            "a": _StubField("a"),
            "rel": _StubField("rel", "many2one", relational=True, comodel="m"),
        }
        self.env = _StubEnv(self)

    def sudo(self):
        return self


class TestM2oBypassComodelIdLookup(unittest.TestCase):
    """The eight-case rewrite table documented on the pass itself.

    Permissions are already bypassed (``any!``), so an ``id``-keyed sub-domain
    can be folded into a direct comparison on the many2one column — with False
    (NULL) handled explicitly, since a NULL m2o matches no comodel row.
    """

    def _rewrite(self, outer_op, sub_op, sub_value):
        condition = DomainCondition(
            "rel", outer_op, DomainCondition("id", sub_op, sub_value)
        )
        return optimizations._optimize_m2o_bypass_comodel_id_lookup(
            condition, _StubModel()
        )

    # X deliberately contains False so the -{False} / |{False} adjustments show
    IN_SET = OrderedSet([1, 2, False])
    OUT_SET = OrderedSet([1, 2])
    SUB = Domain("a", "=", 7)

    def test_any_id_in(self):
        # a ANY (id IN X)  =>  a IN (X - {False})
        result = self._rewrite("any!", "in", self.IN_SET)
        self.assertEqual(list(result), [("rel", "in", [1, 2])])

    def test_any_id_not_in(self):
        # a ANY (id NOT IN X)  =>  a NOT IN (X | {False})
        result = self._rewrite("any!", "not in", self.OUT_SET)
        self.assertEqual(list(result), [("rel", "not in", [1, 2, False])])

    def test_any_id_any(self):
        # a ANY (id ANY X)  =>  a ANY X
        result = self._rewrite("any!", "any!", self.SUB)
        self.assertEqual(list(result), [("rel", "any!", [("a", "=", 7)])])

    def test_any_id_not_any(self):
        # a ANY (id NOT ANY X)  =>  a != False AND a NOT ANY X
        result = self._rewrite("any!", "not any!", self.SUB)
        self.assertEqual(
            list(result),
            ["&", ("rel", "!=", False), ("rel", "not any!", [("a", "=", 7)])],
        )

    def test_not_any_id_in(self):
        # a NOT ANY (id IN X)  =>  a NOT IN (X - {False})
        result = self._rewrite("not any!", "in", self.IN_SET)
        self.assertEqual(list(result), [("rel", "not in", [1, 2])])

    def test_not_any_id_not_in(self):
        # a NOT ANY (id NOT IN X)  =>  a IN (X | {False})
        result = self._rewrite("not any!", "not in", self.OUT_SET)
        self.assertEqual(list(result), [("rel", "in", [1, 2, False])])

    def test_not_any_id_any(self):
        # a NOT ANY (id ANY X)  =>  a NOT ANY X
        result = self._rewrite("not any!", "any!", self.SUB)
        self.assertEqual(list(result), [("rel", "not any!", [("a", "=", 7)])])

    def test_not_any_id_not_any(self):
        # a NOT ANY (id NOT ANY X)  =>  a = False OR a ANY X
        result = self._rewrite("not any!", "not any!", self.SUB)
        self.assertEqual(
            list(result),
            ["|", ("rel", "=", False), ("rel", "any!", [("a", "=", 7)])],
        )

    # gates: shapes the pass must leave untouched

    def test_non_bang_any_is_untouched(self):
        # permissions not bypassed ('any'): the fold would skip record rules
        condition = DomainCondition(
            "rel", "any", DomainCondition("id", "in", self.IN_SET)
        )
        result = optimizations._optimize_m2o_bypass_comodel_id_lookup(
            condition, _StubModel()
        )
        self.assertIs(result, condition)

    def test_non_id_subdomain_is_untouched(self):
        condition = DomainCondition(
            "rel", "any!", DomainCondition("a", "in", self.OUT_SET)
        )
        result = optimizations._optimize_m2o_bypass_comodel_id_lookup(
            condition, _StubModel()
        )
        self.assertIs(result, condition)

    def test_unsupported_suboperator_is_untouched(self):
        condition = DomainCondition("rel", "any!", DomainCondition("id", ">", 5))
        result = optimizations._optimize_m2o_bypass_comodel_id_lookup(
            condition, _StubModel()
        )
        self.assertIs(result, condition)

    def test_non_condition_subdomain_is_untouched(self):
        condition = DomainCondition(
            "rel", "any!", Domain("a", "=", 1) & Domain("a", "=", 2)
        )
        result = optimizations._optimize_m2o_bypass_comodel_id_lookup(
            condition, _StubModel()
        )
        self.assertIs(result, condition)


class TestAnyWithRights(unittest.TestCase):
    """``any``/``not any`` escalate to their record-rule-bypassing ``!`` forms
    exactly when the environment is superuser or the field opts out of search
    access (``bypass_search_access``)."""

    SUB = Domain("a", "=", 7)

    def _model(self, *, su, bypass):
        model = _StubModel()
        model.env.su = su
        model._fields["rel"].bypass_search_access = bypass
        return model

    def test_superuser_escalates_any(self):
        condition = DomainCondition("rel", "any", self.SUB)
        result = optimizations._optimize_any_with_rights(
            condition, self._model(su=True, bypass=False)
        )
        self.assertEqual(result.operator, "any!")
        self.assertIs(result.value, self.SUB)

    def test_superuser_escalates_not_any(self):
        condition = DomainCondition("rel", "not any", self.SUB)
        result = optimizations._optimize_any_with_rights(
            condition, self._model(su=True, bypass=False)
        )
        self.assertEqual(result.operator, "not any!")
        self.assertIs(result.value, self.SUB)

    def test_bypass_search_access_escalates_without_su(self):
        condition = DomainCondition("rel", "any", self.SUB)
        result = optimizations._optimize_any_with_rights(
            condition, self._model(su=False, bypass=True)
        )
        self.assertEqual(result.operator, "any!")

    def test_plain_user_keeps_record_rules(self):
        condition = DomainCondition("rel", "any", self.SUB)
        result = optimizations._optimize_any_with_rights(
            condition, self._model(su=False, bypass=False)
        )
        self.assertIs(result, condition)


class TestInRequiredRemainingGates(unittest.TestCase):
    """The ``_optimize_in_required`` gates not already covered by
    ``test_optimize_unit.TestInRequiredPredicateSafety`` (which locks the
    strip, the ``_predicate_fallback`` attachment and the NewId gate)."""

    def _model(self, field):
        model = _StubModel()
        model._fields[field.name] = field
        model._ids = (1, 2)
        model.env.registry = types.SimpleNamespace(not_null_fields={field})
        return model

    def test_no_false_in_value_returns_same_node(self):
        # fast path: nothing to strip, no field/registry lookup at all
        field = _StubField("rel", "many2one", relational=True, comodel="m")
        field.required = True
        condition = DomainCondition("rel", "in", OrderedSet([1, 2]))
        result = optimizations._optimize_in_required(condition, self._model(field))
        self.assertIs(result, condition)

    def test_id_field_strips_without_required_flag(self):
        # 'id' is NOT NULL by nature: the strip applies even with required=False
        field = _StubField("id")
        condition = DomainCondition("id", "in", OrderedSet([False, 5]))
        result = optimizations._optimize_in_required(condition, self._model(field))
        self.assertIsNot(result, condition)
        self.assertEqual(list(result.value), [5])
        self.assertIs(result._predicate_fallback, condition)

    def test_falsy_value_field_is_untouched(self):
        # a required char column aliases '' with NULL: False in the set still
        # matches empty strings, so stripping it would change the result
        field = _StubField("code", "char")
        field.required = True
        field.falsy_value = ""
        condition = DomainCondition("code", "in", OrderedSet([False, "x"]))
        result = optimizations._optimize_in_required(condition, self._model(field))
        self.assertIs(result, condition)

    def test_field_without_not_null_constraint_is_untouched(self):
        # required in Python but not NOT NULL in the DB (e.g. freshly added
        # column): the SQL may still hold NULLs, keep the False check
        field = _StubField("rel", "many2one", relational=True, comodel="m")
        field.required = True
        model = self._model(field)
        model.env.registry.not_null_fields = set()
        condition = DomainCondition("rel", "in", OrderedSet([False, 5]))
        result = optimizations._optimize_in_required(condition, model)
        self.assertIs(result, condition)


class TestFieldSearchMethodLadder(unittest.TestCase):
    """``_optimize_field_search_method`` resolves a searchable field through a
    fallback ladder; each rung is pinned here, including the operator order in
    which ``determine_domain`` is consulted."""

    def _field(self, handlers, calls):
        """Stub field whose determine_domain serves ``handlers[op]``.

        A handler may be a domain list, a callable(value) -> domain list, an
        exception instance to raise, or absent (returns NotImplemented).
        """
        field = _StubField("f", "char")
        field.search = True

        def determine_domain(model, op, value):
            calls.append(op)
            handler = handlers.get(op, NotImplemented)
            if isinstance(handler, Exception):
                raise handler
            if callable(handler):
                return handler(value)
            return handler

        field.determine_domain = determine_domain
        return field

    def _model(self, handlers, calls, name="f"):
        model = _StubModel()
        field = self._field(handlers, calls)
        field.name = name
        model._fields[name] = field
        return model

    def test_direct_result_is_parsed_as_internal_domain(self):
        calls = []
        model = self._model({"in": [("a", "=", 1)]}, calls)
        result = DomainCondition(
            "f", "in", OrderedSet([1])
        )._optimize_field_search_method(model)
        self.assertEqual(calls, ["in"])
        self.assertEqual(list(result), [("a", "=", 1)])

    def test_negative_operator_retries_with_positive_and_negates(self):
        # 'not in' unimplemented -> retry 'in', wrap the result in a negation
        calls = []
        model = self._model({"in": [("a", "=", 1)]}, calls)
        result = DomainCondition(
            "f", "not in", OrderedSet([1])
        )._optimize_field_search_method(model)
        self.assertEqual(calls, ["not in", "in"])
        self.assertEqual(list(result), [("a", "!=", 1)])

    def test_in_falls_back_to_or_of_equalities(self):
        # neither 'in' nor 'not in' implemented -> one '=' call per element,
        # OR-ed together (the documented "fields implementing only '='" rung)
        calls = []
        model = self._model({"=": lambda v: [("a", "=", v)]}, calls)
        result = DomainCondition(
            "f", "in", OrderedSet([1, 2])
        )._optimize_field_search_method(model)
        self.assertEqual(calls, ["in", "not in", "=", "="])
        self.assertEqual(list(result), ["|", ("a", "=", 1), ("a", "=", 2)])

    def test_not_in_falls_back_to_and_of_inequalities(self):
        calls = []
        model = self._model({"!=": lambda v: [("a", "!=", v)]}, calls)
        result = DomainCondition(
            "f", "not in", OrderedSet([1, 2])
        )._optimize_field_search_method(model)
        self.assertEqual(calls, ["not in", "in", "!=", "!="])
        self.assertEqual(list(result), ["&", ("a", "!=", 1), ("a", "!=", 2)])

    def test_any_bang_falls_back_to_any_with_sudo_and_warns(self):
        # 'any!' raising NotImplementedError -> retried as 'any' on model.sudo()
        # (not strictly equivalent: the search then runs sudo), with a warning
        calls = []
        sub_domain = Domain("a", "=", 3)
        handlers = {
            "any!": NotImplementedError("no any!"),
            "any": [("a", "=", 3)],
        }
        model = self._model(handlers, calls, name="g")
        model._fields["g"].type = "many2one"
        model._fields["g"].relational = True
        model._fields["g"].comodel_name = "m"
        with self.assertLogs("odoo.domains", level="WARNING") as captured:
            result = DomainCondition(
                "g", "any!", sub_domain
            )._optimize_field_search_method(model)
        self.assertEqual(calls, ["any!", "any"])
        self.assertEqual(list(result), [("a", "=", 3)])
        self.assertTrue(
            any("should implement any! operator" in msg for msg in captured.output),
            captured.output,
        )

    def test_original_exception_wins_over_later_fallback_failures(self):
        # determine_domain('in') raises: the '=' rung is still attempted, but
        # when it fails too, the FIRST exception is re-raised (not the later one)
        calls = []
        model = self._model({"in": NotImplementedError("boom-in")}, calls)
        with self.assertRaisesRegex(NotImplementedError, "boom-in"):
            DomainCondition("f", "in", OrderedSet([1]))._optimize_field_search_method(
                model
            )
        # inverse retry is skipped once an exception is recorded; '=' still ran
        self.assertEqual(calls, ["in", "="])

    def test_nothing_implemented_raises_user_error(self):
        # the ladder bottom: no rung applies for 'like' -> UserError built from
        # the field / model descriptions

        class _EnvWithIrModel(_StubEnv):
            def __getitem__(self, name):
                if name == "ir.model":
                    return types.SimpleNamespace(
                        _get=lambda n: types.SimpleNamespace(name="Model M")
                    )
                return self._model

            def _(self, source, **kwargs):
                return source % kwargs

        calls = []
        model = self._model({}, calls)
        model._fields["f"].get_description = lambda env, attrs: {"string": "Field F"}
        model.env = _EnvWithIrModel(model)
        with self.assertRaisesRegex(UserError, "Unsupported operator"):
            DomainCondition("f", "like", "x")._optimize_field_search_method(model)
        # 'like' then its inverse 'not like'; no set-expansion rung for 'like'
        self.assertEqual(calls, ["like", "not like"])
