import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


class MailTrackingDurationMixin(models.AbstractModel):
    # The rotting feature enables resources to mark themselves as stale if enough time has passed
    # since their stage was last updated.
    # Consult _is_rotting_feature_enabled() documentation for configuration instructions
    _name = "mail.tracking.duration.mixin"
    _description = "Mixin to compute the time a record has spent in each value a many2one field can take"
    _inherit = ["mail.thread"]

    # Name of the datetime field holding the last time the tracked value
    # changed, used by the rotting feature. Subclasses that rename it (e.g.
    # project.task -> "date_last_status_change") only override this attribute
    # instead of re-implementing every rotting method.
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

    def _compute_duration_tracking(self):
        """
        Computes duration_tracking, a Json field stored as { <many2one_id (str)>: <duration_spent_in_seconds (int)> }

            e.g. {"1": 1230, "2": 2220, "5": 14}

        `_track_duration_field` must be present in the model that uses the mixin to specify on what
        field to compute time spent. Besides, tracking must be activated for that field.

            e.g.
            class MyModel(models.Model):
                _name = 'my.model'
                _track_duration_field = "tracked_field"

                tracked_field = fields.Many2one('tracked.model', tracking=True)
        """

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
            # Misconfiguration is a developer error, but this is a non-stored
            # compute rendered in list/kanban/form views: raising here would 500
            # the whole view. Degrade gracefully (no duration) and log loudly.
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

        # Bucket the single fetch once by res_id instead of rescanning the full
        # tracking list per record (was O(records x trackings)). The SQL is
        # ordered by v.id, so append preserves per-record chronological order.
        trackings_by_res = defaultdict(list)
        for tracking in trackings:
            trackings_by_res[tracking["res_id"]].append(tracking)
        for record in self:
            # Copy: _get_duration_from_tracking appends synthetic entries to the
            # list it receives. Records sharing an _origin.id -- every unsaved
            # NewId shares False -- would otherwise accumulate each other's
            # buckets, so the second record reported the first one's stage times.
            record.duration_tracking = record._get_duration_from_tracking(
                list(trackings_by_res[record._origin.id])
            )

    @api.depends(lambda self: self._get_rotting_depends_fields())
    def _compute_rotting(self):
        """
        A resource is rotting if its stage has not been updated in a number of days depending on its
        stage's rotting_threshold_days value, assuming it matches _get_rotting_domain() conditions.

        If the rotting_threshold_days field is not defined on the tracked module,
        or if the value of rotting_threshold_days is 0,
        then the resource will never rot.
        """
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

    def _search_is_rotting(self, operator, value):
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
        self.flush_model(model_depends)  # flush fields to make sure DB is up to date
        self.env[self[self._track_duration_field]._name].flush_model(
            ["rotting_threshold_days"]
        )
        base_query = self._search(self._get_rotting_domain())

        # Our query needs to JOIN the stage field's table.
        # This JOIN needs to use the same alias as the base query to avoid non-matching alias issues
        # Note that query objects do not make their alias table available trivially,
        # but the alias can be inferred by consulting the _joins attribute and compare it to the result of make_alias()
        stage_table_alias_name = base_query.make_alias(
            self._table, self._track_duration_field
        )

        # We only need to add a JOIN if the stage table is not already present in the query's _joins attribute.
        from_add_join = ""
        if not base_query._joins or stage_table_alias_name not in base_query._joins:
            from_add_join = """
                INNER JOIN %(stage_table)s AS %(stage_table_alias_name)s
                    ON %(stage_table_alias_name)s.id = %(table)s.%(stage_field)s
            """

        # Items with a date_last_stage_update inferior to that number of months will not be returned by the search function.
        max_rotting_months = self.env["ir.config_parameter"]._get_int_param(
            "crm.lead.rot.max.months", 12
        )

        # We use a F-string so that the from_add_join is added with its %s parameters before the query string is processed
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

    def _get_duration_from_tracking(self, trackings):
        """Calculate the duration spent in each value from the given trackings.

        A "fake" tracking is appended to account for the time spent in the current value.

        :param trackings: list of tracking dicts, each with a ``create_date`` and an
            ``old_value_integer`` (the ID of the previous value).
        :return: dict mapping each value ID to its duration in seconds.
        """
        self.ensure_one()
        json = defaultdict(lambda: 0)
        previous_date = self.create_date or self.env.cr.now()

        # If there is a tracking value to be created, but still in the
        # precommit values, create a fake one to take it into account.
        # Otherwise, the duration_tracking value will add time spent on
        # previous tracked field value to the time spent in the new value
        # (after writing the stage on the record)
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

        # add "fake" tracking for time spent in the current value
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

    def _get_rotting_depends_fields(self):
        """
        fields added to this method through override should likely also be returned by _get_rotting_domain() override

        :return: the array of fields that can affect the ability of a resource to rot
        """
        if (
            hasattr(self, "_track_duration_field")
            and "rotting_threshold_days" in self[self._track_duration_field]
        ):
            return [
                self._track_duration_last_update_field,
                f"{self._track_duration_field}.rotting_threshold_days",
            ]
        return []

    def _get_rotting_domain(self):
        """
        fields added to this method through override should likely also be returned by _get_rotting_depends_fields() override

        :return: domain: conditions that must be met so that the field can be considered rotting
        """
        return Domain(f"{self._track_duration_field}.rotting_threshold_days", "!=", 0)

    def _is_rotting_feature_enabled(self):
        """Rotting requires the '_track_duration_field' target model to have an
        integer 'rotting_threshold_days' (days before a record rots), and this
        model to have a stage-change tracking field
        ('_track_duration_last_update_field').

        :return: bool: whether the rotting feature has been configured for this model
        """
        return (
            "rotting_threshold_days" in self[self._track_duration_field]
            and self._track_duration_last_update_field in self
            and (
                not self  # api.model call
                or any(
                    stage.rotting_threshold_days
                    for stage in self[self._track_duration_field]
                )
            )
        )
