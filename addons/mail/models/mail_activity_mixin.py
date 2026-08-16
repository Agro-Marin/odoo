import logging
import typing
from collections.abc import Sequence
from datetime import date, datetime
from types import NotImplementedType
from typing import Any, Literal

from odoo import api, fields, models
from odoo.api import DomainType
from odoo.fields import Domain
from odoo.tools import SQL, Query, partition

if typing.TYPE_CHECKING:
    from .mail_activity import MailActivity
    from .mail_activity_type import MailActivityType
    from odoo.addons.bus.models.res_users import ResUsers

_logger = logging.getLogger(__name__)


class MailActivityMixin(models.AbstractModel):
    _name = "mail.activity.mixin"
    _description = "Activity Mixin"

    def _default_activity_type(self) -> MailActivityType:
        return self.env["mail.activity"]._default_activity_type_for_model(self._name)

    activity_ids: MailActivity = fields.One2many(
        "mail.activity",
        "res_id",
        "Activities",
        bypass_search_access=True,
        groups="base.group_user",
    )
    activity_state = fields.Selection(
        [("overdue", "Overdue"), ("today", "Today"), ("planned", "Planned")],
        string="Activity State",
        compute="_compute_activity_state",
        search="_search_activity_state",
        groups="base.group_user",
        help="Status based on activities\nOverdue: Due date is already passed\n"
        "Today: Activity date is today\nPlanned: Future activities.",
    )
    activity_user_id: ResUsers = fields.Many2one(
        "res.users",
        "Responsible User",
        compute="_compute_activity_user_id",
        readonly=True,
        search="_search_activity_user_id",
        groups="base.group_user",
    )
    activity_type_id: MailActivityType = fields.Many2one(
        "mail.activity.type",
        "Next Activity Type",
        compute="_compute_activity_next",
        inverse="_inverse_activity_type_id",
        search="_search_activity_type_id",
        readonly=False,
        groups="base.group_user",
    )
    activity_type_icon = fields.Char(
        "Activity Type Icon",
        compute="_compute_activity_next",
        groups="base.group_user",
    )
    activity_date_deadline = fields.Date(
        "Next Activity Deadline",
        compute="_compute_activity_date_deadline",
        search="_search_activity_date_deadline",
        compute_sudo=False,
        readonly=True,
        store=False,
        groups="base.group_user",
    )
    my_activity_date_deadline = fields.Date(
        "My Activity Deadline",
        compute="_compute_my_activity_date_deadline",
        search="_search_my_activity_date_deadline",
        compute_sudo=False,
        readonly=True,
        groups="base.group_user",
    )
    activity_summary = fields.Char(
        "Next Activity Summary",
        compute="_compute_activity_next",
        inverse="_inverse_activity_summary",
        search="_search_activity_summary",
        readonly=False,
        groups="base.group_user",
    )
    activity_exception_decoration = fields.Selection(
        [("warning", "Alert"), ("danger", "Error")],
        compute="_compute_activity_exception_type",
        search="_search_activity_exception_decoration",
        groups="base.group_user",
        help="Type of the exception activity on record.",
    )
    activity_exception_icon = fields.Char(
        "Icon",
        help="Icon to indicate an exception activity.",
        compute="_compute_activity_exception_type",
        groups="base.group_user",
    )

    @api.depends(
        "activity_ids.active",
        "activity_ids.activity_type_id.decoration_type",
        "activity_ids.activity_type_id.icon",
    )
    def _compute_activity_exception_type(self) -> None:
        self.mapped("activity_ids.activity_type_id.decoration_type")

        for record in self:
            activity_types = record.activity_ids.activity_type_id
            exception_activity_type = next(
                (
                    activity_type
                    for activity_type in activity_types
                    if activity_type.decoration_type == "danger"
                ),
                None,
            ) or next(
                (
                    activity_type
                    for activity_type in activity_types
                    if activity_type.decoration_type == "warning"
                ),
                None,
            )
            record.activity_exception_decoration = (
                exception_activity_type and exception_activity_type.decoration_type
            )
            record.activity_exception_icon = (
                exception_activity_type and exception_activity_type.icon
            )

    @api.depends("activity_ids.active", "activity_ids.user_id")
    def _compute_activity_user_id(self) -> None:
        self.mapped("activity_ids.user_id")
        for record in self:
            record.activity_user_id = record.activity_ids[:1].user_id

    @api.depends(
        "activity_ids.active",
        "activity_ids.summary",
        "activity_ids.activity_type_id",
        "activity_ids.activity_type_id.icon",
    )
    def _compute_activity_next(self) -> None:
        self.mapped("activity_ids.summary")
        self.mapped("activity_ids.activity_type_id.icon")
        for record in self:
            activity = record.activity_ids[:1]
            record.activity_summary = activity.summary
            record.activity_type_id = activity.activity_type_id
            record.activity_type_icon = activity.activity_type_id.icon

    def _inverse_activity_summary(self) -> None:
        for record in self:
            record.activity_ids[:1].summary = record.activity_summary

    def _inverse_activity_type_id(self) -> None:
        for record in self:
            record.activity_ids[:1].activity_type_id = record.activity_type_id

    @api.depends("activity_ids.active", "activity_ids.state")
    def _compute_activity_state(self) -> None:
        for record in self:
            states = record.activity_ids.mapped("state")
            if "overdue" in states:
                record.activity_state = "overdue"
            elif "today" in states:
                record.activity_state = "today"
            elif "planned" in states:
                record.activity_state = "planned"
            else:
                record.activity_state = False

    def _open_activity_domain(self, subdomain: Sequence[tuple] = ()) -> Domain:
        return Domain(
            "activity_ids", "any", Domain([("active", "=", True), *subdomain])
        )

    def _next_activity_domain(
        self, subdomain: Sequence[tuple], user_id: int | None = None
    ) -> Domain:
        first_ids = self.env["mail.activity"]._sql_first_activity_ids(
            self._name, user_id=user_id
        )
        return self._open_activity_domain([("id", "in", first_ids), *subdomain])

    def _search_next_activity_field(
        self,
        fname: str,
        operator: str,
        operand: Any,
        user_id: int | None = None,
    ) -> Domain | NotImplementedType:
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        domain = self._next_activity_domain(
            [(fname, operator, operand)], user_id=user_id
        )
        if operator == "in" and False in operand:
            domain |= ~self._open_activity_domain(
                [("user_id", "=", user_id)] if user_id is not None else ()
            )
        return domain

    def _search_activity_state(
        self, operator: str, value: Any
    ) -> Domain | NotImplementedType:
        all_states = {"overdue", "today", "planned", False}
        if operator == "in":
            search_states = set(value)
        elif operator == "not in":
            search_states = all_states - set(value)
        else:
            return NotImplemented

        reverse_search = False
        if False in search_states:
            reverse_search = True
            search_states = all_states - search_states

        if not search_states:
            matching = Domain.FALSE
        elif search_states == all_states - {False}:
            matching = self._open_activity_domain()
        else:
            Activity = self.env["mail.activity"]
            Activity.flush_model(
                ["active", "date_deadline", "res_id", "res_model", "user_id", "user_tz"]
            )
            integer_state_value = {"overdue": -1, "today": 0, "planned": 1}
            query = SQL(
                """(
                SELECT res_id
                    FROM (
                        SELECT res_id, MIN(%(activity_state)s) AS activity_state
                        FROM mail_activity
                        WHERE mail_activity.res_model = %(res_model_table)s
                          AND mail_activity.active = true
                    GROUP BY res_id
                    ) AS res_record
                -- Cast the parameter to integer[]: psycopg adapts the small-int
                -- list (-1/0/1) as smallint[], but activity_state is SIGN(...)::INT
                -- (integer[]), and PG18 has no `smallint[] @> integer[]` operator.
                WHERE %(search_states_int)s::integer[] @> ARRAY[activity_state]
                )""",
                activity_state=Activity._sql_state(),
                res_model_table=self._name,
                search_states_int=[integer_state_value[s] for s in search_states],
            )
            matching = Domain("id", "in", query)

        return ~matching if reverse_search else matching

    @api.depends("activity_ids.active", "activity_ids.date_deadline")
    def _compute_activity_date_deadline(self) -> None:
        self.mapped("activity_ids.date_deadline")
        for record in self:
            record.activity_date_deadline = record.activity_ids[:1].date_deadline

    def _search_activity_date_deadline(
        self, operator: str, operand: Any
    ) -> Domain | NotImplementedType:
        return self._search_next_activity_field("date_deadline", operator, operand)

    def _search_activity_user_id(
        self, operator: str, operand: Any
    ) -> Domain | NotImplementedType:
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        if operator != "in":
            return self._search_next_activity_field("user_id", operator, operand)
        bools, values = partition(lambda v: isinstance(v, bool), operand)
        domain = Domain.FALSE
        if True in bools:
            domain |= self._next_activity_domain([("user_id", "!=", False)])
        if False in bools:
            domain |= (
                self._next_activity_domain([("user_id", "=", False)])
                | ~self._open_activity_domain()
            )
        if values:
            domain |= self._search_next_activity_field("user_id", "in", values)
        return domain

    def _search_activity_type_id(
        self, operator: str, operand: Any
    ) -> Domain | NotImplementedType:
        return self._search_next_activity_field("activity_type_id", operator, operand)

    def _search_activity_summary(
        self, operator: str, operand: Any
    ) -> Domain | NotImplementedType:
        return self._search_next_activity_field("summary", operator, operand)

    def _search_activity_exception_decoration(
        self, operator: str, operand: Any
    ) -> Domain | NotImplementedType:
        if operator != "in":
            return NotImplemented
        danger = self._open_activity_domain(
            [("activity_type_id.decoration_type", "=", "danger")]
        )
        warning = self._open_activity_domain(
            [("activity_type_id.decoration_type", "=", "warning")]
        )
        domain_by_value = {
            "danger": danger,
            "warning": warning & ~danger,
            False: ~danger & ~warning,
        }
        domain = Domain.FALSE
        for value in set(operand):
            domain |= domain_by_value.get(value or False, Domain.FALSE)
        return domain

    @api.depends(
        "activity_ids.active", "activity_ids.date_deadline", "activity_ids.user_id"
    )
    @api.depends_context("uid")
    def _compute_my_activity_date_deadline(self) -> None:
        for record in self:
            record.my_activity_date_deadline = next(
                (
                    activity.date_deadline
                    for activity in record.activity_ids
                    if activity.user_id.id == record.env.uid
                ),
                False,
            )

    def _search_my_activity_date_deadline(
        self, operator: str, operand: Any
    ) -> Domain | NotImplementedType:
        return self._search_next_activity_field(
            "date_deadline", operator, operand, user_id=self.env.uid
        )

    def _read_group_groupby(self, alias: str, groupby_spec: str, query: Query) -> SQL:
        if groupby_spec != "activity_state":
            return super()._read_group_groupby(alias, groupby_spec, query)
        self._check_field_access(self._fields["activity_state"], "read")

        Activity = self.env["mail.activity"]
        Activity.flush_model(
            ["active", "date_deadline", "res_model", "res_id", "user_id", "user_tz"]
        )

        sql_join = SQL(
            """
            (SELECT res_id,
                CASE MIN(%(activity_state)s)
                    WHEN -1 THEN 'overdue'
                    WHEN 0 THEN 'today'
                    WHEN 1 THEN 'planned'
                END AS activity_state
            FROM mail_activity
            WHERE res_model = %(res_model)s AND mail_activity.active = true
            GROUP BY res_id)
            """,
            activity_state=Activity._sql_state(),
            res_model=self._name,
        )
        alias = query.left_join(
            self._table, "id", sql_join, "res_id", "last_activity_state"
        )

        return SQL.identifier(alias, "activity_state")

    def _reschedule_my_next_activity(self, action: str) -> dict | Literal[False]:
        my_next_activities = self.env["mail.activity"]
        for record in self:
            my_next_activities += record.activity_ids.filtered(
                lambda activity: activity.user_id == self.env.user
            )[:1]
        return getattr(my_next_activities, action)()

    def action_reschedule_my_next_today(self) -> dict | Literal[False]:
        return self._reschedule_my_next_activity("action_reschedule_today")

    def action_reschedule_my_next_tomorrow(self) -> dict | Literal[False]:
        return self._reschedule_my_next_activity("action_reschedule_tomorrow")

    def action_reschedule_my_next_nextweek(self) -> dict | Literal[False]:
        return self._reschedule_my_next_activity("action_reschedule_nextweek")

    def activity_send_mail(self, template_id: int) -> bool:
        template = self.env["mail.template"].browse(template_id).exists()
        if not template or template.model != self._name:
            if template:
                _logger.warning(
                    "Refused to send template %s (model %s) on %s",
                    template.id,
                    template.model,
                    self._name,
                )
            return False
        self.message_post_with_source(
            template,
            subtype_xmlid="mail.mt_comment",
        )
        return True

    def _activity_type_ids(self, act_type_xmlids: list[str]) -> list:
        Data = self.env["ir.model.data"].sudo()
        return [
            type_id
            for type_id in (
                Data._xmlid_to_res_id(xmlid, raise_if_not_found=False)
                for xmlid in act_type_xmlids
            )
            if type_id
        ]

    def activity_search(
        self,
        act_type_xmlids: tuple[str, ...] = (),
        user_id: int | None = None,
        additional_domain: DomainType | None = None,
        only_automated: bool = True,
    ) -> MailActivity:
        if self.env.context.get("mail_activity_automation_skip"):
            return self.env["mail.activity"]

        activity_types_ids = self._activity_type_ids(act_type_xmlids)
        if not activity_types_ids:
            return self.env["mail.activity"]

        domain = Domain(
            [
                ("res_model", "=", self._name),
                ("res_id", "in", self.ids),
                ("activity_type_id", "in", activity_types_ids),
            ]
        )

        if only_automated:
            domain &= Domain("automated", "=", True)
        if user_id:
            domain &= Domain("user_id", "=", user_id)
        if additional_domain:
            domain &= Domain(additional_domain)

        return self.env["mail.activity"].search(domain)

    def activity_schedule(
        self,
        act_type_xmlid: str = "",
        date_deadline: date | None = None,
        summary: str = "",
        note: str = "",
        **act_values,
    ) -> MailActivity:
        if self.env.context.get("mail_activity_automation_skip"):
            return self.env["mail.activity"]

        return self._activity_create(
            self._activity_type_for_schedule(act_type_xmlid, act_values),
            date_deadline,
            summary,
            dict.fromkeys(self._ids, note),
            act_values,
        )

    def _activity_type_for_schedule(
        self, act_type_xmlid: str, act_values: dict
    ) -> MailActivityType:
        if act_type_xmlid:
            activity_type_id = self.env["ir.model.data"]._xmlid_to_res_id(
                act_type_xmlid, raise_if_not_found=False
            )
            if not activity_type_id:
                _logger.warning(
                    "Unknown activity type xml id %s on %s, falling back on the "
                    "model's default type",
                    act_type_xmlid,
                    self._name,
                )
        else:
            activity_type_id = act_values.get("activity_type_id", False)
        activity_type = self.env["mail.activity.type"].browse(activity_type_id)
        if activity_type.res_model and activity_type.res_model != self._name:
            _logger.warning(
                "Invalid activity type model %s used on %s (tried with xml id %s)",
                activity_type.res_model,
                self._name,
                act_type_xmlid or "",
            )
        return activity_type or self._default_activity_type()

    def _activity_create(
        self,
        activity_type: MailActivityType,
        date_deadline: date | None,
        summary: str,
        notes: dict[int, str],
        act_values: dict,
    ) -> MailActivity:
        if not date_deadline:
            date_deadline = fields.Date.context_today(self)
        if isinstance(date_deadline, datetime):
            _logger.warning(
                "Scheduled deadline should be a date (got %s)", date_deadline
            )
        model_id = self.env["ir.model"]._get(self._name).id
        create_vals_list = []
        for record in self:
            create_vals = {
                "activity_type_id": activity_type.id,
                "summary": summary or activity_type.summary,
                "automated": True,
                "note": notes.get(record.id) or activity_type.default_note,
                "date_deadline": date_deadline,
                "res_model_id": model_id,
                "res_id": record.id,
            }
            create_vals.update(act_values)
            if not create_vals.get("user_id") and activity_type.default_user_id:
                create_vals["user_id"] = activity_type.default_user_id.id
            create_vals_list.append(create_vals)
        return self.env["mail.activity"].create(create_vals_list)

    def _activity_schedule_with_view(
        self,
        act_type_xmlid: str = "",
        date_deadline: date | None = None,
        summary: str = "",
        views_or_xmlid: models.BaseModel | str = "",
        render_context: dict | None = None,
        **act_values,
    ) -> MailActivity:
        if self.env.context.get("mail_activity_automation_skip"):
            return self.env["mail.activity"]

        view_ref = (
            views_or_xmlid.id
            if isinstance(views_or_xmlid, models.BaseModel)
            else views_or_xmlid
        )
        base_context = render_context or {}
        notes = {
            record.id: self.env["ir.qweb"]._render(
                view_ref,
                {**base_context, "object": record},
                minimal_qcontext=True,
                raise_if_not_found=False,
            )
            for record in self
        }
        return self._activity_create(
            self._activity_type_for_schedule(act_type_xmlid, act_values),
            date_deadline,
            summary,
            notes,
            act_values,
        )

    def activity_reschedule(
        self,
        act_type_xmlids: list[str],
        user_id: int | None = None,
        date_deadline: date | None = None,
        new_user_id: int | None = None,
        only_automated: bool = True,
    ) -> MailActivity:
        activities = self.activity_search(
            act_type_xmlids, user_id=user_id, only_automated=only_automated
        )
        if activities:
            write_vals = {}
            if date_deadline:
                write_vals["date_deadline"] = date_deadline
            if new_user_id:
                write_vals["user_id"] = new_user_id
            activities.write(write_vals)
        return activities

    def activity_feedback(
        self,
        act_type_xmlids: list[str],
        user_id: int | None = None,
        feedback: str | None = None,
        attachment_ids: list[int] | None = None,
        only_automated: bool = True,
    ) -> MailActivity:
        activities = self.activity_search(
            act_type_xmlids, user_id=user_id, only_automated=only_automated
        )
        if activities:
            activities.action_feedback(feedback=feedback, attachment_ids=attachment_ids)
        return activities

    def activity_unlink(
        self,
        act_type_xmlids: list[str],
        user_id: int | None = None,
        only_automated: bool = True,
    ) -> MailActivity:
        activities = self.activity_search(
            act_type_xmlids, user_id=user_id, only_automated=only_automated
        )
        activities.unlink()
        return activities
