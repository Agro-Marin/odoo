import typing
from datetime import date
from typing import Literal

from dateutil.relativedelta import relativedelta

from odoo import _, api, exceptions, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError

if typing.TYPE_CHECKING:
    from .mail_template import MailTemplate
    from odoo.addons.bus.models.res_users import ResUsers


class MailActivityType(models.Model):
    _name = "mail.activity.type"
    _description = "Activity Type"
    _order = "sequence, id"
    _rec_name = "name"

    def _get_model_selection(self) -> list:
        return [
            (model.model, model.name)
            for model in self.env["ir.model"]
            .sudo()
            .search(["&", ("is_mail_thread", "=", True), ("transient", "=", False)])
        ]

    name = fields.Char("Name", required=True, translate=True)
    summary = fields.Char("Default Summary", translate=True)
    sequence = fields.Integer("Sequence", default=10)
    active = fields.Boolean(default=True)
    create_uid: ResUsers = fields.Many2one("res.users", index=True)
    delay_count = fields.Integer(
        "Schedule",
        default=0,
        help="Number of days/week/month before executing the action. It allows to plan the action deadline.",
    )
    delay_unit = fields.Selection(
        [("days", "days"), ("weeks", "weeks"), ("months", "months")],
        string="Delay units",
        help="Unit of delay",
        required=True,
        default="days",
    )
    delay_label = fields.Char(compute="_compute_delay_label")
    delay_from = fields.Selection(
        [
            ("current_date", "after previous activity completion date"),
            ("previous_activity", "after previous activity deadline"),
        ],
        string="Delay Type",
        help="Type of delay",
        required=True,
        default="previous_activity",
    )
    icon = fields.Char("Icon", help="Font awesome icon e.g. fa-tasks")
    decoration_type = fields.Selection(
        [("warning", "Alert"), ("danger", "Error")],
        string="Decoration Type",
        help="Change the background color of the related activities of this type.",
    )
    res_model = fields.Selection(
        selection=_get_model_selection,
        string="Model",
        help="Specify a model if the activity should be specific to a model"
        " and not available when managing activities for other models.",
    )
    triggered_next_type_id: MailActivityType = fields.Many2one(
        "mail.activity.type",
        string="Trigger",
        compute="_compute_triggered_next_type_id",
        inverse="_inverse_triggered_next_type_id",
        store=True,
        readonly=False,
        domain="['|', ('res_model', '=', False), ('res_model', '=', res_model)]",
        ondelete="restrict",
        help="Automatically schedule this activity once the current one is marked as done.",
    )
    chaining_type = fields.Selection(
        [("suggest", "Suggest Next Activity"), ("trigger", "Trigger Next Activity")],
        string="Chaining Type",
        required=True,
        default="suggest",
    )
    suggested_next_type_ids: MailActivityType = fields.Many2many(
        "mail.activity.type",
        "mail_activity_rel",
        "activity_id",
        "recommended_id",
        string="Suggest",
        domain="['|', ('res_model', '=', False), ('res_model', '=', res_model)]",
        compute="_compute_suggested_next_type_ids",
        inverse="_inverse_suggested_next_type_ids",
        store=True,
        readonly=False,
        help="Suggest these activities once the current one is marked as done.",
    )
    previous_type_ids: MailActivityType = fields.Many2many(
        "mail.activity.type",
        "mail_activity_rel",
        "recommended_id",
        "activity_id",
        domain="['|', ('res_model', '=', False), ('res_model', '=', res_model)]",
        string="Preceding Activities",
    )
    category = fields.Selection(
        [
            ("default", "None"),
            ("upload_file", "Upload Document"),
            ("phonecall", "Phonecall"),
        ],
        default="default",
        string="Action",
        help="Actions may trigger specific behavior like opening calendar view or automatically mark as done when a document is uploaded",
    )
    mail_template_ids: MailTemplate = fields.Many2many(
        "mail.template", string="Email templates"
    )
    default_user_id: ResUsers = fields.Many2one("res.users", string="Default User")
    default_note = fields.Html(string="Default Note", translate=True)

    initial_res_model = fields.Selection(
        selection=_get_model_selection,
        string="Initial model",
        compute="_compute_initial_res_model",
        store=False,
        help="Technical field to keep track of the model at the start of editing to support UX related behaviour",
    )
    res_model_change = fields.Boolean(
        string="Model has change", default=False, store=False
    )

    @api.constrains("res_model")
    def _check_activity_type_res_model(self) -> None:
        self.env["mail.activity.plan.template"].search(
            [("activity_type_id", "in", self.ids)]
        )._check_activity_type_res_model()

    @api.onchange("res_model")
    def _onchange_res_model(self) -> None:
        self.mail_template_ids = self.sudo().mail_template_ids.filtered(
            lambda template: template.model_id.model == self.res_model
        )
        self.res_model_change = (
            self.initial_res_model and self.initial_res_model != self.res_model
        )

    def _compute_initial_res_model(self) -> None:
        for activity_type in self:
            activity_type.initial_res_model = activity_type.res_model

    @api.depends("delay_unit", "delay_count")
    def _compute_delay_label(self) -> None:
        selection_description_values = {
            e[0]: e[1]
            for e in self._fields["delay_unit"]._description_selection(self.env)
        }
        for activity_type in self:
            unit = selection_description_values[activity_type.delay_unit]
            activity_type.delay_label = "%s %s" % (activity_type.delay_count, unit)

    @api.depends("chaining_type")
    def _compute_suggested_next_type_ids(self) -> None:
        for activity_type in self:
            if activity_type.chaining_type == "trigger":
                activity_type.suggested_next_type_ids = False

    def _inverse_suggested_next_type_ids(self) -> None:
        for activity_type in self:
            if activity_type.suggested_next_type_ids:
                activity_type.chaining_type = "suggest"

    @api.depends("chaining_type")
    def _compute_triggered_next_type_id(self) -> None:
        for activity_type in self:
            if activity_type.chaining_type == "suggest":
                activity_type.triggered_next_type_id = False

    def _inverse_triggered_next_type_id(self) -> None:
        for activity_type in self:
            if activity_type.triggered_next_type_id:
                activity_type.chaining_type = "trigger"
            else:
                activity_type.chaining_type = "suggest"

    def write(self, vals: ValuesType) -> Literal[True]:
        if "res_model" in vals:
            xmlid_to_model = {
                xmlid: info["res_model"]
                for xmlid, info in self._get_model_info_by_xmlid().items()
            }
            modified = self.browse()
            for xml_id, model in xmlid_to_model.items():
                activity_type = self.env.ref(xml_id, raise_if_not_found=False)
                if (
                    activity_type
                    and (vals["res_model"] or False) != (model or False)
                    and activity_type in self
                ):
                    modified += activity_type
            if modified:
                raise exceptions.UserError(
                    _(
                        "You cannot modify %(activities_names)s target model as they are are required in various apps.",
                        activities_names=", ".join(act.name for act in modified),
                    )
                )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_todo(self) -> None:
        master_data = self.browse()
        for xml_id in [
            xmlid
            for xmlid, info in self._get_model_info_by_xmlid().items()
            if info["unlink"] is False
        ]:
            activity_type = self.env.ref(xml_id, raise_if_not_found=False)
            if activity_type and activity_type in self:
                master_data += activity_type
        if master_data:
            raise exceptions.UserError(
                _(
                    "You cannot delete %(activity_names)s as it is required in various apps.",
                    activity_names=", ".join(act.name for act in master_data),
                )
            )

    def action_archive(self) -> bool:
        if self.env.ref("mail.mail_activity_data_todo") in self:
            raise UserError(
                _(
                    "The 'To-Do' activity type is used to create reminders from the top bar menu and the command palette. Consequently, it cannot be archived or deleted."
                )
            )
        return super().action_archive()

    def unlink(self) -> Literal[True]:
        todo_type = self.env.ref("mail.mail_activity_data_todo")
        self.env["mail.activity"].sudo().with_context(active_test=False).search(
            [("activity_type_id", "in", self.ids)]
        ).write(
            {
                "activity_type_id": todo_type.id,
            }
        )
        return super().unlink()

    def _get_date_deadline(self) -> date:
        self.ensure_one()
        if self.delay_from == "previous_activity" and self.env.context.get(
            "activity_previous_deadline"
        ):
            base = fields.Date.from_string(
                self.env.context.get("activity_previous_deadline")
            )
        else:
            base = fields.Date.context_today(self)
        return base + relativedelta(**{self.delay_unit: self.delay_count})

    @api.model
    def _get_model_info_by_xmlid(self) -> dict:
        return {
            "mail.mail_activity_data_call": {"res_model": False, "unlink": False},
            "mail.mail_activity_data_meeting": {"res_model": False, "unlink": False},
            "mail.mail_activity_data_todo": {"res_model": False, "unlink": False},
            "mail.mail_activity_data_upload_document": {
                "res_model": False,
                "unlink": True,
            },
            "mail.mail_activity_data_warning": {"res_model": False, "unlink": True},
        }
