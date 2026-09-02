import typing
import unittest
from datetime import date, datetime
from unittest.mock import patch

from odoo.libs.collections import OrderedSet
from odoo.libs.datetime import utc
from odoo.orm.domain.ast import Domain, DomainCondition, OptimizationLevel
from odoo.orm.fields import temporal
from odoo.orm.fields.numeric import Integer
from odoo.orm.fields.relational.many2one import Many2one
from odoo.orm.fields.temporal import Date, Datetime

if typing.TYPE_CHECKING:
    from odoo.orm.models import BaseModel


def _as_model(stub: object) -> BaseModel:
    return typing.cast("BaseModel", stub)


def _field(field_class, name, **attrs):
    field = field_class.__new__(field_class)
    field.name = name
    field.model_name = "m"
    field.comodel_name = None
    field.store = True
    field.required = False
    field.inherited = False
    field.related = None
    field.company_dependent = False
    field.search = None
    field.determine_domain = None
    for key, value in attrs.items():
        setattr(field, key, value)
    return field


class _StubEnv:
    tz = utc
    su = True
    registry: typing.Any = None

    def __init__(self, model):
        self._model = model

    def __getitem__(self, model_name):
        return self._model


class _StubModel:
    _name = "m"
    _auto = True
    _ids: tuple = ()

    def __init__(self):
        self._fields = {
            "a": _field(Integer, "a"),
            "d": _field(Date, "d"),
            "dt": _field(Datetime, "dt"),
            "rel": _field(Many2one, "rel", comodel_name="m"),
        }
        self.env = _StubEnv(self)

    def _check_field_access(self, field, operation):
        pass

    def sudo(self):
        return self


def _opt(domain):
    return list(domain.optimize(_as_model(_StubModel())))


def _hook(field_name, condition, level):
    model = _StubModel()
    field = model._fields[field_name]
    return field._optimize_condition(condition, _as_model(model), level)


class TestDatetimeEqualityGranularity(unittest.TestCase):
    def test_eq_datetime_is_exact(self):
        self.assertEqual(
            _opt(Domain("dt", "=", datetime(2024, 1, 1, 10, 30, 15, 123456))),
            [("dt", "in", [datetime(2024, 1, 1, 10, 30, 15, 123456)])],
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
        self.assertEqual(
            _opt(Domain("dt", "in", [date(2024, 1, 1), datetime(2024, 3, 4, 5, 6, 7)])),
            [
                "|",
                ("dt", "in", [datetime(2024, 3, 4, 5, 6, 7)]),
                "&",
                ("dt", "<", datetime(2024, 1, 2)),
                ("dt", ">=", datetime(2024, 1, 1)),
            ],
        )

    def test_eq_max_date_has_no_upper_bound(self):
        self.assertEqual(
            _opt(Domain("dt", "=", date(9999, 12, 31))),
            [("dt", ">=", datetime(9999, 12, 31))],
        )

    def test_eq_today_resolves_to_whole_day(self):
        with patch.object(
            temporal, "parse_date_expression", return_value=date(2024, 1, 5)
        ):
            self.assertEqual(
                list(Domain("dt", "=", "today").optimize_full(_as_model(_StubModel()))),
                [
                    "&",
                    ("dt", "<", datetime(2024, 1, 6)),
                    ("dt", ">=", datetime(2024, 1, 5)),
                ],
            )

    def test_eq_lt_gt_date_partition_the_axis(self):
        d = date(2024, 1, 1)
        self.assertEqual(
            _opt(Domain("dt", "<", d)), [("dt", "<", datetime(2024, 1, 1))]
        )
        self.assertEqual(
            _opt(Domain("dt", ">", d)), [("dt", ">=", datetime(2024, 1, 2))]
        )


class TestRelativePassSkipsWithoutStrings(unittest.TestCase):
    def test_datetime_set_without_strings_is_same_object(self):
        condition = DomainCondition("dt", "in", OrderedSet([datetime(2024, 1, 1)]))
        result = _hook("dt", condition, OptimizationLevel.DYNAMIC_VALUES)
        self.assertIs(result, condition)

    def test_date_set_without_strings_is_same_object(self):
        condition = DomainCondition("d", "in", OrderedSet([date(2024, 1, 1)]))
        result = _hook("d", condition, OptimizationLevel.DYNAMIC_VALUES)
        self.assertIs(result, condition)

    def test_set_with_string_still_resolves(self):
        condition = DomainCondition(
            "dt", "in", OrderedSet(["today", datetime(2024, 3, 4, 5, 6, 7)])
        )
        with patch.object(
            temporal, "parse_date_expression", return_value=date(2024, 1, 5)
        ):
            result = _hook("dt", condition, OptimizationLevel.DYNAMIC_VALUES)
        self.assertIsNot(result, condition)
        self.assertEqual(
            list(result.value), [date(2024, 1, 5), datetime(2024, 3, 4, 5, 6, 7)]
        )


class TestBasicPassSkipsNoOpRebuild(unittest.TestCase):
    def test_datetime_scalar_already_converted_is_same_object(self):
        condition = DomainCondition("dt", ">=", datetime(2024, 1, 1))
        result = _hook("dt", condition, OptimizationLevel.BASIC)
        self.assertIs(result, condition)

    def test_datetime_set_without_datetimes_is_same_object(self):
        condition = DomainCondition("dt", "in", OrderedSet([False]))
        result = _hook("dt", condition, OptimizationLevel.BASIC)
        self.assertIs(result, condition)

    def test_datetime_conversion_still_rebuilds(self):
        condition = DomainCondition("dt", ">", date(2024, 1, 1))
        result = _hook("dt", condition, OptimizationLevel.BASIC)
        self.assertIsNot(result, condition)
        self.assertEqual((result.operator, result.value), (">=", datetime(2024, 1, 2)))


class TestM2oBypassComodelIdLookup(unittest.TestCase):
    IN_SET = OrderedSet([1, 2, False])
    OUT_SET = OrderedSet([1, 2])
    SUB = Domain("a", "=", 7)

    def _rewrite(self, outer_op, sub_op, sub_value):
        condition = DomainCondition(
            "rel", outer_op, DomainCondition("id", sub_op, sub_value)
        )
        return _hook("rel", condition, OptimizationLevel.FULL)

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
        self.assertIs(_hook("rel", condition, OptimizationLevel.FULL), condition)

    def test_non_id_subdomain_is_untouched(self):
        condition = DomainCondition(
            "rel", "any!", DomainCondition("a", "in", self.OUT_SET)
        )
        self.assertIs(_hook("rel", condition, OptimizationLevel.FULL), condition)

    def test_unsupported_suboperator_is_untouched(self):
        condition = DomainCondition("rel", "any!", DomainCondition("id", ">", 5))
        self.assertIs(_hook("rel", condition, OptimizationLevel.FULL), condition)

    def test_non_condition_subdomain_is_untouched(self):
        condition = DomainCondition(
            "rel", "any!", Domain("a", "=", 1) & Domain("a", "=", 2)
        )
        self.assertIs(_hook("rel", condition, OptimizationLevel.FULL), condition)
