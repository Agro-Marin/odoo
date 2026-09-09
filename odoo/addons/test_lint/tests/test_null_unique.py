import ast
from textwrap import dedent

from odoo.tests.common import BaseCase, no_retry

from . import _checker_null_unique as checker


@no_retry
class TestNullUniqueChecker(BaseCase):
    @staticmethod
    def _units(**sources):
        return [
            (f"{name}.py", checker.collect(ast.parse(dedent(source))))
            for name, source in sources.items()
        ]

    def _findings(self, **sources):
        return list(checker.violations(self._units(**sources)))

    def test_flags_a_composite_unique_over_a_nullable_column(self):
        found = self._findings(
            a="""
            class Charge(models.Model):
                _name = "a.charge"
                employee_id = fields.Many2one("hr.employee", required=True)
                asset_id = fields.Many2one("stock.lot")
                date = fields.Date(required=True)
                _uniq = models.Constraint("UNIQUE (employee_id, asset_id, date)", "one")
            """
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].nullable, ("asset_id",))
        self.assertEqual(found[0].columns, ("employee_id", "asset_id", "date"))

    def test_ignores_a_composite_whose_columns_are_all_required(self):
        self.assertFalse(
            self._findings(
                a="""
                class Line(models.Model):
                    _name = "a.line"
                    order_id = fields.Many2one("a.order", required=True)
                    sequence = fields.Integer(required=True)
                    _uniq = models.Constraint("UNIQUE (order_id, sequence)", "one")
                """
            ),
            "no column can be NULL, so PostgreSQL exempts nothing",
        )

    def test_ignores_a_single_column_unique_on_an_optional_value(self):
        self.assertFalse(
            self._findings(
                a="""
                class Lot(models.Model):
                    _name = "a.lot"
                    imei = fields.Char()
                    _uniq = models.Constraint("UNIQUE (imei)", "one")
                """
            ),
            "NULL means 'not set' and repeated unset rows are the point; "
            "flagging this would bank a correct construct as debt",
        )

    def test_accepts_nulls_not_distinct_as_the_answer(self):
        self.assertFalse(
            self._findings(
                a="""
                class Charge(models.Model):
                    _name = "a.charge"
                    employee_id = fields.Many2one("hr.employee", required=True)
                    asset_id = fields.Many2one("stock.lot")
                    _uniq = models.UniqueIndex(
                        "(employee_id, asset_id) NULLS NOT DISTINCT", "one"
                    )
                """
            ),
            "the key is declared to hold over the empty rows",
        )

    def test_accepts_a_partial_index_as_the_answer(self):
        self.assertFalse(
            self._findings(
                a="""
                class Event(models.Model):
                    _name = "a.event"
                    device_id = fields.Many2one("a.device", required=True)
                    event_uid = fields.Char()
                    _uniq = models.UniqueIndex(
                        "(device_id, event_uid) WHERE event_uid IS NOT NULL", "one"
                    )
                """
            ),
            "the exemption is declared rather than inherited from a NULL rule",
        )

    def test_ignores_a_functional_index(self):
        self.assertFalse(
            self._findings(
                a="""
                class Level(models.Model):
                    _name = "a.level"
                    profile_id = fields.Many2one("a.profile", required=True)
                    warehouse_id = fields.Many2one("stock.warehouse")
                    _uniq = models.UniqueIndex(
                        "(profile_id, COALESCE(warehouse_id, 0))", "one"
                    )
                """
            ),
            "COALESCE is how a key folds its own NULLs; judging the rest needs "
            "semantics this checker does not have",
        )

    def test_sees_a_column_another_module_declares_required(self):
        self.assertFalse(
            self._findings(
                a="""
                class Device(models.Model):
                    _name = "a.device"
                    identifier = fields.Char(required=True)
                    company_id = fields.Many2one("res.company")
                    _uniq = models.Constraint(
                        "UNIQUE (identifier, company_id)", "one"
                    )
                """,
                b="""
                class DeviceBridge(models.Model):
                    _inherit = "a.device"
                    company_id = fields.Many2one("res.company", required=True)
                """,
            ),
            "one required=True anywhere is what puts NOT NULL on the column, so "
            "a per-file scan would report a column that cannot be NULL",
        )

    def test_leaves_a_column_it_never_saw_declared_alone(self):
        self.assertFalse(
            self._findings(
                a="""
                class Move(models.Model):
                    _inherit = "account.move"
                    _uniq = models.Constraint(
                        "UNIQUE (name, company_id)", "one"
                    )
                """
            ),
            "neither column is declared in the scanned tree, so nullability is "
            "unknown and guessing would invent findings",
        )

    def test_inherits_required_through_a_mixin(self):
        self.assertFalse(
            self._findings(
                a="""
                class Thing(models.Model):
                    _name = "a.thing"
                    _inherit = ["a.mixin"]
                    code = fields.Char(required=True)
                    _uniq = models.Constraint("UNIQUE (code, company_id)", "one")
                """,
                b="""
                class Mixin(models.AbstractModel):
                    _name = "a.mixin"
                    company_id = fields.Many2one("res.company", required=True)
                """,
            ),
            "the mixin settles company_id for every model that composes it",
        )

    def test_survives_an_inherit_cycle(self):
        found = self._findings(
            a="""
            class One(models.Model):
                _name = "a.one"
                _inherit = ["a.two"]
                left = fields.Char()
                _uniq = models.Constraint("UNIQUE (left, right)", "one")
            """,
            b="""
            class Two(models.Model):
                _name = "a.two"
                _inherit = ["a.one"]
                right = fields.Char(required=True)
            """,
        )
        self.assertEqual([f.nullable for f in found], [("left",)])

    def test_ignores_a_non_unique_constraint(self):
        self.assertFalse(
            self._findings(
                a="""
                class Charge(models.Model):
                    _name = "a.charge"
                    amount = fields.Float()
                    _check = models.Constraint("CHECK (amount >= 0)", "one")
                """
            )
        )
