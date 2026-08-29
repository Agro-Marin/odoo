from odoo import fields, models
from odoo.libs.sql import SQL

# Concrete models the mixins' own tests run against.
#
# They are registered unconditionally, following this fork's convention for
# test models (`approval.test.document`), because the defects these mixins
# shipped with were all invisible to a suite that patched the abstract mixins
# in place: a stand-alone model's own `_table_query` shadows a mixin property,
# a missing `id` index only exists once a relation is really created, and a
# rolling window only reaches its column list on the *second* tick. None of
# that can be reached without real models.
#
# The cost is three tiny relations over one small table in every database that
# installs this module.


class ReportTestSource(models.Model):
    _name = "mixin.report.sql.test.source"
    _description = "SQL Report Test Source"

    date = fields.Date()
    grain = fields.Char()
    value = fields.Float()


class ReportTestPlain(models.Model):
    """`mixin.sql.report` alone: the ORM inlines the query as a subquery."""

    _name = "mixin.report.sql.test.plain"
    _inherit = ["mixin.sql.report"]
    _description = "SQL Report Test (not materialized)"
    _auto = False

    grain = fields.Char(readonly=True)
    total = fields.Float(readonly=True)
    rows = fields.Integer(readonly=True)

    def _get_fields_select(self) -> dict:
        return {
            "id": "MIN(s.id)",
            "grain": "s.grain",
            "total": "SUM(s.value)",
            "rows": "COUNT(*)",
        }

    def _get_from_tables(self) -> list:
        return [("mixin_report_sql_test_source", "s", None, None)]

    def _get_fields_group_by(self) -> list:
        return ["s.grain"]


class ReportTestMv(models.Model):
    """Materialized, with the unique index deliberately NOT on ``id``.

    That is the shape `invoice.line.in.report` ships, and the one that used to
    leave `id` with no index at all.
    """

    _name = "mixin.report.sql.test.mv"
    _inherit = ["mixin.sql.report", "mixin.materialized.view"]
    _description = "SQL Report Test (materialized view)"
    _auto = False
    _relation_index_field = "grain"

    grain = fields.Char(readonly=True)
    total = fields.Float(readonly=True)

    def _get_fields_select(self) -> dict:
        return {
            "id": "MIN(s.id)",
            "grain": "s.grain",
            "total": "SUM(s.value)",
        }

    def _get_from_tables(self) -> list:
        return [("mixin_report_sql_test_source", "s", None, None)]

    def _get_fields_group_by(self) -> list:
        return ["s.grain"]


class ReportTestRolling(models.Model):
    _name = "mixin.report.sql.test.rolling"
    _inherit = ["mixin.sql.report", "mixin.rolling.report"]
    _description = "SQL Report Test (rolling window)"
    _auto = False
    _rolling_key_field = "date"
    _rolling_window_days = 3

    date = fields.Date(readonly=True)
    grain = fields.Char(readonly=True)
    total = fields.Float(readonly=True)

    def _rolling_scope(self) -> SQL:
        return SQL(
            "(SELECT * FROM mixin_report_sql_test_source WHERE date >= %s) s",
            self._rolling_cutoff_sql(),
        )

    def _get_fields_select(self) -> dict:
        return {
            "id": "MIN(s.id)",
            "date": "s.date",
            "grain": "s.grain",
            "total": "SUM(s.value)",
        }

    def _get_from_tables(self) -> list:
        return [
            (
                self._rolling_scope_sql() or SQL("mixin_report_sql_test_source s"),
                None,
                None,
                None,
            )
        ]

    def _get_fields_group_by(self) -> list:
        return ["s.date", "s.grain"]
