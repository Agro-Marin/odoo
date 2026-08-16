import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


class MailTrackingDurationMixin(models.AbstractModel):
    _name = "mail.tracking.duration.mixin"
    _description = "Mixin to compute the time a record has spent in each value a many2one field can take"
    _inherit = ["mail.thread"]

    _track_duration_last_update_field = "date_last_stage_update"

    duration_tracking = fields.Json(
        string="Status time",
        compute="_compute_duration_tracking",
        help="JSON that maps ids from a many2one field to seconds spent",
    )
    rotting_days = fields.Integer(
        "Days Rotting",
        compute="_compute_rotting",
        help="Day count since this resource was last updated",
    )
    is_rotting = fields.Boolean(
        "Rotting",
        compute="_compute_rotting",
        search="_search_is_rotting",
    )

    def _get_duration_tracking_depends_fields(self) -> list:
        field_name = getattr(self, "_track_duration_field", None)
        return [field_name] if field_name else []

    @api.depends(lambda self: self._get_duration_tracking_depends_fields())
    def _compute_duration_tracking(self) -> None:
        field = (
            self.env["ir.model.fields"]
            .sudo()
            .search_fetch(
                [
                    ("model", "=", self._name),
                    ("name", "=", self._track_duration_field),
                ],
                ["id"],
                limit=1,
            )
        )

        if (
            self._track_duration_field not in self._track_get_fields()
            or self._fields[self._track_duration_field].type != "many2one"
        ):
            _logger.warning(
                "Field %r on model %r must be a tracked Many2one for duration "
                "tracking; leaving duration_tracking empty.",
                self._track_duration_field,
                self._name,
            )
            self.duration_tracking = False
            return

        if self.ids:
            self.env["mail.tracking.value"].flush_model()
            self.env["mail.message"].flush_model()
            trackings = self.env.execute_query_dict(
                SQL(
                    """
                   SELECT m.res_id,
                          v.create_date,
                          v.old_value_integer
                     FROM mail_tracking_value v
                LEFT JOIN mail_message m
                       ON m.id = v.mail_message_id
                      AND v.field_id = %(field_id)s
                    WHERE m.model = %(model_name)s
                      AND m.res_id IN %(record_ids)s
                 ORDER BY v.id
                """,
                    field_id=field.id,
                    model_name=self._name,
                    record_ids=tuple(self.ids),
                )
            )
        else:
            trackings = []

        trackings_by_res = defaultdict(list)
        for tracking in trackings:
            trackings_by_res[tracking["res_id"]].append(tracking)
        for record in self:
            record.duration_tracking = record._get_duration_from_tracking(
                list(trackings_by_res[record._origin.id])
            )

    @api.depends(lambda self: self._get_rotting_depends_fields())
    def _compute_rotting(self) -> None:
        if not self._is_rotting_feature_enabled():
            self.is_rotting = False
            self.rotting_days = 0
            return
        now = self.env.cr.now()
        last_update_field = self._track_duration_last_update_field
        rot_enabled = self.filtered_domain(self._get_rotting_domain())
        others = self - rot_enabled
        for stage, records in rot_enabled.grouped(self._track_duration_field).items():
            rotting = records.filtered(
                lambda record: (
                    (
                        record[last_update_field]
                        or record.create_date
                        or fields.Datetime.now()
                    )
                    + timedelta(days=stage.rotting_threshold_days)  # noqa: B023
                    < now
                )
            )
            for record in rotting:
                record.is_rotting = True
                record.rotting_days = (
                    now - (record[last_update_field] or record.create_date)
                ).days
            others += records - rotting
        others.is_rotting = False
        others.rotting_days = 0

    def _search_is_rotting(self, operator: str, value: Any) -> list:
        if operator not in ["in", "not in"]:
            raise ValueError(
                self.env._(
                    'For performance reasons, use "=" operators on rotting fields.'
                )
            )
        if not self._is_rotting_feature_enabled():
            raise UserError(
                self.env._("Model configuration does not support the rotting feature")
            )
        model_depends = [
            fname for fname in self._get_rotting_depends_fields() if "." not in fname
        ]
        self.flush_model(model_depends)
        self.env[self[self._track_duration_field]._name].flush_model(
            ["rotting_threshold_days"]
        )
        base_query = self._search(self._get_rotting_domain())

        stage_table_alias_name = base_query.make_alias(
            self._table, self._track_duration_field
        )

        from_add_join = ""
        if not base_query._joins or stage_table_alias_name not in base_query._joins:
            from_add_join = """
                INNER JOIN %(stage_table)s AS %(stage_table_alias_name)s
                    ON %(stage_table_alias_name)s.id = %(table)s.%(stage_field)s
            """

        icp = self.env["ir.config_parameter"]
        max_rotting_months = icp._get_int_param(
            "mail.rotting.max.months",
            icp._get_int_param("crm.lead.rot.max.months", 12),
        )

        query = f"""
            WITH perishables AS (
                SELECT  %(table)s.id AS id,
                        (
                            %(table)s.%(last_update_field)s + %(stage_table_alias_name)s.rotting_threshold_days * interval '1 day'
                        ) AS date_rot
                FROM %(from_clause)s
                    {from_add_join}
                WHERE
                    %(table)s.%(last_update_field)s > %(today)s - make_interval(months => %(max_rotting_months)s)
                    AND %(where_clause)s
            )
            SELECT id
            FROM perishables
            WHERE %(today)s >= date_rot

        """
        self.env.cr.execute(
            SQL(
                query,
                table=SQL.identifier(self._table),
                last_update_field=SQL.identifier(
                    self._track_duration_last_update_field
                ),
                stage_table=SQL.identifier(self[self._track_duration_field]._table),
                stage_table_alias_name=SQL.identifier(stage_table_alias_name),
                stage_field=SQL.identifier(self._track_duration_field),
                today=self.env.cr.now(),
                where_clause=base_query.where_clause,
                from_clause=base_query.from_clause,
                max_rotting_months=max_rotting_months,
            )
        )
        rows = self.env.cr.dictfetchall()
        return [("id", operator, [r["id"] for r in rows])]

    def _get_duration_from_tracking(self, trackings: list[dict]) -> dict:
        self.ensure_one()
        json = defaultdict(lambda: 0)
        previous_date = self.create_date or self.env.cr.now()

        if f"mail.tracking.{self._name}" in self.env.cr.precommit.data:
            if data := self.env.cr.precommit.data.get(
                f"mail.tracking.{self._name}", {}
            ).get(self._origin.id):
                new_id = data.get(self._track_duration_field, self.env[self._name]).id
                if new_id and new_id != self[self._track_duration_field].id:
                    trackings.append(
                        {
                            "create_date": self.env.cr.now(),
                            "old_value_integer": data[self._track_duration_field].id,
                        }
                    )

        trackings.append(
            {
                "create_date": self.env.cr.now(),
                "old_value_integer": self[self._track_duration_field].id,
            }
        )

        for tracking in trackings:
            json[tracking["old_value_integer"]] += int(
                (tracking["create_date"] - previous_date).total_seconds()
            )
            previous_date = tracking["create_date"]

        return json

    def _get_rotting_depends_fields(self) -> list:
        if (
            hasattr(self, "_track_duration_field")
            and "rotting_threshold_days" in self[self._track_duration_field]
        ):
            return [
                self._track_duration_last_update_field,
                f"{self._track_duration_field}.rotting_threshold_days",
            ]
        return []

    def _get_rotting_domain(self) -> Domain:
        return Domain(f"{self._track_duration_field}.rotting_threshold_days", "!=", 0)

    def _is_rotting_feature_enabled(self) -> bool:
        return (
            "rotting_threshold_days" in self[self._track_duration_field]
            and self._track_duration_last_update_field in self
            and (
                not self
                or any(
                    stage.rotting_threshold_days
                    for stage in self[self._track_duration_field]
                )
            )
        )
