import types
import unittest

from odoo.exceptions import UserError
from odoo.libs.collections import OrderedSet
from odoo.orm.domain import optimizations
from odoo.orm.domain.ast import Domain, DomainCondition


class _StubField:
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
    _auto = True

    def __init__(self):
        self._fields = {
            "a": _StubField("a"),
            "rel": _StubField("rel", "many2one", relational=True, comodel="m"),
        }
        self.env = _StubEnv(self)

    def sudo(self):
        return self


class TestM2oBypassComodelIdLookup(unittest.TestCase):
    def _rewrite(self, outer_op, sub_op, sub_value):
        condition = DomainCondition(
            "rel", outer_op, DomainCondition("id", sub_op, sub_value)
        )
        return optimizations._optimize_m2o_bypass_comodel_id_lookup(
            condition, _StubModel()
        )

    IN_SET = OrderedSet([1, 2, False])
    OUT_SET = OrderedSet([1, 2])
    SUB = Domain("a", "=", 7)

    def test_any_id_in(self):
        result = self._rewrite("any!", "in", self.IN_SET)
        self.assertEqual(list(result), [("rel", "in", [1, 2])])

    def test_any_id_not_in(self):
        result = self._rewrite("any!", "not in", self.OUT_SET)
        self.assertEqual(list(result), [("rel", "not in", [1, 2, False])])

    def test_any_id_any(self):
        result = self._rewrite("any!", "any!", self.SUB)
        self.assertEqual(list(result), [("rel", "any!", [("a", "=", 7)])])

    def test_any_id_not_any(self):
        result = self._rewrite("any!", "not any!", self.SUB)
        self.assertEqual(
            list(result),
            ["&", ("rel", "!=", False), ("rel", "not any!", [("a", "=", 7)])],
        )

    def test_not_any_id_in(self):
        result = self._rewrite("not any!", "in", self.IN_SET)
        self.assertEqual(list(result), [("rel", "not in", [1, 2])])

    def test_not_any_id_not_in(self):
        result = self._rewrite("not any!", "not in", self.OUT_SET)
        self.assertEqual(list(result), [("rel", "in", [1, 2, False])])

    def test_not_any_id_any(self):
        result = self._rewrite("not any!", "any!", self.SUB)
        self.assertEqual(list(result), [("rel", "not any!", [("a", "=", 7)])])

    def test_not_any_id_not_any(self):
        result = self._rewrite("not any!", "not any!", self.SUB)
        self.assertEqual(
            list(result),
            ["|", ("rel", "=", False), ("rel", "any!", [("a", "=", 7)])],
        )

    def test_non_bang_any_is_untouched(self):
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
    def _model(self, field):
        model = _StubModel()
        model._fields[field.name] = field
        model._ids = (1, 2)
        model.env.registry = types.SimpleNamespace(not_null_fields={field})
        return model

    def test_no_false_in_value_returns_same_node(self):
        field = _StubField("rel", "many2one", relational=True, comodel="m")
        field.required = True
        condition = DomainCondition("rel", "in", OrderedSet([1, 2]))
        result = optimizations._optimize_in_required(condition, self._model(field))
        self.assertIs(result, condition)

    def test_id_field_strips_without_required_flag(self):
        field = _StubField("id")
        condition = DomainCondition("id", "in", OrderedSet([False, 5]))
        result = optimizations._optimize_in_required(condition, self._model(field))
        self.assertIsNot(result, condition)
        self.assertEqual(list(result.value), [5])
        self.assertIs(result._predicate_fallback, condition)

    def test_falsy_value_field_is_untouched(self):
        field = _StubField("code", "char")
        field.required = True
        field.falsy_value = ""
        condition = DomainCondition("code", "in", OrderedSet([False, "x"]))
        result = optimizations._optimize_in_required(condition, self._model(field))
        self.assertIs(result, condition)

    def test_field_without_not_null_constraint_is_untouched(self):
        field = _StubField("rel", "many2one", relational=True, comodel="m")
        field.required = True
        model = self._model(field)
        model.env.registry.not_null_fields = set()
        condition = DomainCondition("rel", "in", OrderedSet([False, 5]))
        result = optimizations._optimize_in_required(condition, model)
        self.assertIs(result, condition)


class TestFieldSearchMethodLadder(unittest.TestCase):
    def _field(self, handlers, calls):
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
        calls = []
        model = self._model({"in": [("a", "=", 1)]}, calls)
        result = DomainCondition(
            "f", "not in", OrderedSet([1])
        )._optimize_field_search_method(model)
        self.assertEqual(calls, ["not in", "in"])
        self.assertEqual(list(result), [("a", "!=", 1)])

    def test_in_falls_back_to_or_of_equalities(self):
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
        calls = []
        model = self._model({"in": NotImplementedError("boom-in")}, calls)
        with self.assertRaisesRegex(NotImplementedError, "boom-in"):
            DomainCondition("f", "in", OrderedSet([1]))._optimize_field_search_method(
                model
            )
        self.assertEqual(calls, ["in", "="])

    def test_nothing_implemented_raises_user_error(self):

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
        self.assertEqual(calls, ["like", "not like"])


class TestResetOptCopyUndoesAModelDependentRewrite(unittest.TestCase):
    """A domain optimized for one model must not carry its rewrite to another.

    ``_optimize_in_required`` strips ``False`` from an ``in`` set because the
    field is NOT NULL *on that model*. ``_reset_opt_copy`` reset the
    optimization level and copied every other slot, so the strip survived into
    the copy and the next model inherited an answer that was never true for it.
    """

    def _model(self, field, *, not_null):
        model = _StubModel()
        model._fields[field.name] = field
        model._ids = (1, 2)
        model.env.registry = types.SimpleNamespace(
            not_null_fields={field} if not_null else set()
        )
        return model

    def test_the_strip_does_not_survive_into_another_model(self):
        strict_field = _StubField("rel", "many2one", relational=True, comodel="m")
        strict_field.required = True
        loose_field = _StubField("rel", "many2one", relational=True, comodel="m")
        loose_field.required = False

        original = DomainCondition("rel", "in", OrderedSet([False, 5]))
        stripped = optimizations._optimize_in_required(
            original, self._model(strict_field, not_null=True)
        )
        self.assertEqual(list(stripped.value), [5], "test premise: it strips")

        reset = stripped._reset_opt_copy()
        self.assertEqual(
            list(reset.value),
            [False, 5],
            "the reset copy kept the strip the previous model justified",
        )

    def test_the_reset_copy_drops_the_stale_fallback(self):
        field = _StubField("rel", "many2one", relational=True, comodel="m")
        field.required = True
        original = DomainCondition("rel", "in", OrderedSet([False, 5]))
        stripped = optimizations._optimize_in_required(
            original, self._model(field, not_null=True)
        )
        reset = stripped._reset_opt_copy()
        self.assertIsNone(
            getattr(reset, "_predicate_fallback", None),
            "a fallback naming the previous model's strip must not ride along",
        )

    def test_a_condition_with_no_fallback_is_copied_as_before(self):
        condition = DomainCondition("rel", "in", OrderedSet([1, 2]))
        reset = condition._reset_opt_copy()
        self.assertIsNot(reset, condition)
        self.assertEqual(list(reset.value), [1, 2])
        self.assertEqual(reset.field_expr, "rel")
        self.assertEqual(reset.operator, "in")
