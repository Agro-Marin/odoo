import base64
import logging
import typing
from ast import literal_eval
from collections.abc import Collection
from itertools import batched
from types import NotImplementedType
from typing import Any, Literal, Self

from odoo import _, api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools.safe_eval import safe_eval, time

if typing.TYPE_CHECKING:
    from .mail_mail import MailMail
    from odoo.addons.base.models.ir_actions import IrActionsAct_Window
    from odoo.addons.base.models.ir_actions_report import IrActionsReport
    from odoo.addons.base.models.ir_mail_server import IrMail_Server
    from odoo.addons.base.models.ir_model import IrModel
    from odoo.addons.bus.models.ir_attachment import IrAttachment
    from odoo.addons.bus.models.res_users import ResUsers

_logger = logging.getLogger(__name__)

DYNAMIC_FIELD_NAMES = frozenset(
    {
        "body_html",
        "email_cc",
        "email_from",
        "email_to",
        "lang",
        "partner_to",
        "reply_to",
        "scheduled_date",
        "subject",
    }
)

TEMPLATE_SPECIFIC_FIELD_NAMES = frozenset(
    {
        "attachment_ids",
        "auto_delete",
        "email_cc",
        "email_layout_xmlid",
        "email_to",
        "mail_server_id",
        "model",
        "partner_to",
        "report_template_ids",
        "res_id",
        "scheduled_date",
    }
)

RECIPIENT_FIELD_NAMES = frozenset({"email_cc", "email_to", "partner_to"})

ATTACHMENT_FIELD_NAMES = frozenset({"attachment_ids", "report_template_ids"})

VALIDATION_RES_ID = 0
"""Sentinel record id used to render without a record.

Not usable for the save-time render probe, which must keep sampling a real record:
against ``browse(0)`` every Many2one resolves to an empty recordset, so a valid
expression traversing one — ``{{ object.event_id.event_date_range }}``, shipped by
``event`` — hits a compute that calls ``ensure_one()`` and raises. Rejecting a template
that renders fine in production is worse than the sampling non-determinism the sentinel
would have removed. See the 2026-08-15 audit, §2.1.
"""


class MailTemplate(models.Model):
    _name = "mail.template"
    _inherit = ["mail.render.mixin", "template.reset.mixin"]
    _description = "Email Templates"
    _order = "user_id, name, id"

    _unrestricted_rendering = True

    @api.model
    def default_get(self, fields: list[str]) -> ValuesType:
        res = super().default_get(fields)
        if res.get("model"):
            res["model_id"] = self.env["ir.model"]._get(res.pop("model")).id
        return res

    name = fields.Char("Name", translate=True)
    description = fields.Text(
        "Template Description",
        translate=True,
        help="This field is used for internal description of the template's usage.",
    )
    active = fields.Boolean(default=True)
    template_category = fields.Selection(
        [
            ("base_template", "Base Template"),
            ("hidden_template", "Hidden Template"),
            ("custom_template", "Custom Template"),
        ],
        compute="_compute_template_category",
        search="_search_template_category",
    )
    model_id: IrModel = fields.Many2one(
        "ir.model",
        "Applies to",
        ondelete="cascade",
        domain=[("abstract", "=", False)],
    )
    model = fields.Char(
        "Related Document Model",
        related="model_id.model",
        index=True,
        store=True,
        readonly=True,
    )
    subject = fields.Char(
        "Subject",
        translate=True,
        prefetch=True,
        help="Subject (placeholders may be used here)",
    )
    email_from = fields.Char(
        "Send From",
        help="Sender address (placeholders may be used here). If not set, the default "
        "value will be the author's email alias if configured, or email address.",
    )
    user_id: ResUsers = fields.Many2one(
        "res.users", string="Owner", domain="[('share', '=', False)]"
    )
    use_default_to = fields.Boolean(
        "Default Recipients",
        default=True,
        help="Default recipients of the record:\n"
        "- partner (using id on a partner or the partner_id field) OR\n"
        "- email (using email_from or email field)",
    )
    email_to = fields.Char(
        "To (Emails)",
        help="Comma-separated recipient addresses (placeholders may be used here)",
    )
    partner_to = fields.Char(
        "To (Partners)",
        help="Comma-separated ids of recipient partners (placeholders may be used here)",
    )
    email_cc = fields.Char(
        "Cc", help="Carbon copy recipients (placeholders may be used here)"
    )
    reply_to = fields.Char(
        "Reply To",
        help="Email address to which replies will be redirected when sending emails in mass; only used when the reply is not logged in the original discussion thread.",
    )
    body_html = fields.Html(
        "Body",
        render_engine="qweb",
        render_options={"post_process": True},
        prefetch=True,
        translate=True,
        sanitize="email_outgoing",
    )
    attachment_ids: IrAttachment = fields.Many2many(
        "ir.attachment",
        "email_template_attachment_rel",
        "email_template_id",
        "attachment_id",
        string="Attachments",
        bypass_search_access=True,
    )
    report_template_ids: IrActionsReport = fields.Many2many(
        "ir.actions.report",
        relation="mail_template_ir_actions_report_rel",
        column1="mail_template_id",
        column2="ir_actions_report_id",
        string="Dynamic Reports",
        domain="[('model', '=', model)]",
    )
    email_layout_xmlid = fields.Char("Email Notification Layout", copy=False)
    mail_server_id: IrMail_Server = fields.Many2one(
        "ir.mail_server",
        "Outgoing Mail Server",
        readonly=False,
        index="btree_not_null",
        help="Optional preferred server for outgoing mails. If not set, the highest "
        "priority one will be used.",
    )
    scheduled_date = fields.Char(
        "Scheduled Date",
        help="If set, the queue manager will send the email after the date. If not set, the email will be send as soon as possible. You can use dynamic expression.",
    )
    auto_delete = fields.Boolean(
        "Auto Delete",
        default=True,
        help="This option permanently removes any track of email after it's been sent, including from the Technical menu in the Settings, in order to preserve storage space of your Odoo database.",
    )
    ref_ir_act_window: IrActionsAct_Window = fields.Many2one(
        "ir.actions.act_window",
        "Sidebar action",
        readonly=True,
        copy=False,
        help="Sidebar action to make this template available on records "
        "of the related document model",
    )

    can_write = fields.Boolean(
        compute="_compute_can_write", help="The current user can edit the template."
    )
    is_template_editor = fields.Boolean(compute="_compute_is_template_editor")

    has_dynamic_reports = fields.Boolean(compute="_compute_has_dynamic_reports")
    has_mail_server = fields.Boolean(compute="_compute_has_mail_server")

    @api.depends("model")
    def _compute_has_dynamic_reports(self) -> None:
        number_of_dynamic_reports_per_model = dict(
            self.env["ir.actions.report"]
            .sudo()
            ._read_group(
                domain=[("model", "in", self.mapped("model"))],
                groupby=["model"],
                aggregates=["id:count"],
                having=[("__count", ">", 0)],
            )
        )
        for template in self:
            template.has_dynamic_reports = (
                template.model in number_of_dynamic_reports_per_model
            )

    @api.depends()
    def _compute_has_mail_server(self) -> None:
        has_mail_server = bool(self.env["ir.mail_server"].sudo().search([], limit=1))
        for template in self:
            template.has_mail_server = has_mail_server

    @api.depends("model")
    def _compute_render_model(self) -> None:
        for template in self:
            template.render_model = template.model

    @api.depends_context("uid")
    def _compute_can_write(self) -> None:
        writable_ids = set(self._filtered_access("write")._ids)
        for template in self:
            template.can_write = template.id in writable_ids

    @api.depends_context("uid")
    def _compute_is_template_editor(self) -> None:
        self.is_template_editor = self.env.user.has_group(
            "mail.group_mail_template_editor"
        )

    @api.model
    def _get_module_xmlid_domain(self) -> Domain:
        return Domain(
            "id",
            "in",
            self.env["ir.model.data"]
            .sudo()
            ._search([("model", "=", "mail.template"), ("module", "!=", "__export__")])
            .subselect("res_id"),
        )

    def _get_module_owned_ids(self) -> set[int]:
        if not self:
            return set()
        return {
            res_id
            for (res_id,) in self.env["ir.model.data"]
            .sudo()
            ._read_group(
                domain=[
                    ("model", "=", "mail.template"),
                    ("module", "!=", "__export__"),
                    ("res_id", "in", self.ids),
                ],
                groupby=["res_id"],
            )
        }

    @api.depends("active", "description")
    def _compute_template_category(self) -> None:
        deactivated = self.filtered(lambda template: not template.active)
        if deactivated:
            deactivated.template_category = "hidden_template"
        remaining = self - deactivated
        if not remaining:
            return
        module_owned_ids = remaining._get_module_owned_ids()
        for template in remaining:
            if template.id not in module_owned_ids:
                template.template_category = "custom_template"
            elif template.description:
                template.template_category = "base_template"
            else:
                template.template_category = "hidden_template"

    @api.model
    def _search_template_category(
        self, operator: str, value: Any
    ) -> Domain | NotImplementedType:
        if operator != "in":
            return NotImplemented

        module_owned = self._get_module_xmlid_domain()
        domain = Domain.FALSE

        if "hidden_template" in value:
            domain |= Domain("active", "=", False) | (
                Domain("active", "=", True)
                & Domain("description", "=", False)
                & module_owned
            )

        if "base_template" in value:
            domain |= (
                Domain("active", "=", True)
                & Domain("description", "!=", False)
                & module_owned
            )

        if "custom_template" in value:
            domain |= Domain("active", "=", True) & ~module_owned

        return domain

    @api.onchange("model")
    def _onchange_model(self) -> None:
        for template in self.filtered("model"):
            if upd_values := self._get_model_template_defaults(template.model):
                template.update(upd_values)

    def _update_attachment_ownership(self) -> Self:
        for record in self:
            misowned = record.attachment_ids.filtered(
                lambda attachment, record=record: (
                    attachment.res_model != record._name
                    or attachment.res_id != record.id
                )
            )
            if misowned:
                misowned.write({"res_model": record._name, "res_id": record.id})
        return self

    @api.constrains("model_id")
    def _check_model_not_abstract(self) -> None:
        for model in set(self.mapped("model_id.model")):
            if self.env[model]._abstract:
                raise ValidationError(
                    _("You may not define a template on an abstract model: %s", model)
                )

    def _check_rendering(
        self, fnames: set[str] | None = None, render_options: dict | None = None
    ) -> None:
        if self.env.context.get("install_mode"):
            return
        dynamic_fnames = self._get_dynamic_field_names()

        for template in self.sudo():
            template_fnames = fnames & dynamic_fnames if fnames else dynamic_fnames
            if not template_fnames:
                continue
            model = template.model_id.model
            if not model:
                continue
            record = template.env[model].search([], limit=1)
            if not record:
                continue

            for fname in template_fnames:
                try:
                    template._render_field(fname, record.ids, options=render_options)
                except AccessError, MissingError:
                    raise
                except (UserError, ValueError, SyntaxError) as e:
                    _logger.info(
                        "mail.template %s: field %s does not render",
                        template.id,
                        fname,
                        exc_info=True,
                    )
                    raise ValidationError(
                        _(
                            "Oops! We couldn't save your template due to an issue.\n\n"
                            "Error: %(error_details)s\n\n"
                            "Correct it and try again.",
                            error_details=str(e),
                        )
                    ) from e

    @api.model
    def _get_dynamic_field_names(self) -> set[str]:
        return set(DYNAMIC_FIELD_NAMES)

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        records = super().create(vals_list)
        records._check_rendering(fnames=None)
        records._update_attachment_ownership()
        return records

    def write(self, vals: ValuesType) -> Literal[True]:
        super().write(vals)
        self._check_rendering(
            fnames=vals.keys()
            if {"model", "model_id"}.isdisjoint(vals.keys())
            else None
        )
        if "attachment_ids" in vals:
            self._update_attachment_ownership()
        return True

    def unlink(self) -> Literal[True]:
        self.unlink_action()
        return super().unlink()

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        vals_list = super().copy_data(default=default)
        for vals, template in zip(vals_list, self, strict=False):
            if "name" not in (default or {}) and vals.get("name") == template.name:
                vals["name"] = self.env._("%s (copy)", template.name)
        return vals_list

    def copy_translations(self, new: Self, excluded: Collection[str] = ()) -> None:
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    def copy(self, default: ValuesType | None = None) -> Self:
        default = dict(default or {})
        copy_attachments = "attachment_ids" not in default
        if copy_attachments:
            default["attachment_ids"] = False
        copies = super().copy(default=default)

        if copy_attachments:
            for copy, original in zip(copies, self, strict=True):
                if original.attachment_ids:
                    copy.attachment_ids = original.attachment_ids.copy(
                        default={"res_id": copy.id, "res_model": original._name}
                    )
        return copies

    def unlink_action(self) -> bool:
        self.ref_ir_act_window.unlink()
        return True

    def create_action(self) -> bool:
        view = self.env.ref("mail.email_compose_message_wizard_form")
        actions = self.env["ir.actions.act_window"].create(
            [
                {
                    "name": _("Send Mail (%s)", template.name or template.display_name),
                    "type": "ir.actions.act_window",
                    "res_model": "mail.compose.message",
                    "context": repr(
                        {
                            "default_composition_mode": "mass_mail",
                            "default_model": template.model,
                            "default_template_id": template.id,
                        }
                    ),
                    "view_mode": "form,list",
                    "view_id": view.id,
                    "target": "new",
                    "binding_model_id": template.model_id.id,
                }
                for template in self
            ]
        )
        for template, action in zip(self, actions, strict=True):
            template.ref_ir_act_window = action
        return True

    def action_open_mail_preview(self) -> dict:
        self.ensure_one()
        action = self.env.ref("mail.mail_template_preview_action")._get_action_dict()
        action.update(
            {
                "name": _(
                    'Template Preview: "%(template_name)s"', template_name=self.name
                )
            }
        )
        return action

    def _render_report_per_record(
        self, report: IrActionsReport, res_ids: list[int]
    ) -> dict:
        IrActionsReport = self.env["ir.actions.report"]

        if report.report_type in ("qweb-html", "qweb-pdf"):
            batched_streams = self._get_report_streams_batch(report, res_ids)
            if batched_streams is not None:
                return {
                    res_id: (stream.getvalue(), "pdf")
                    for res_id, stream in batched_streams.items()
                }
            return {
                res_id: IrActionsReport._render_qweb_pdf(report, [res_id])
                for res_id in res_ids
            }

        rendered = {}
        for res_id in res_ids:
            render_res = IrActionsReport._render(report, [res_id])
            if not render_res:
                raise UserError(
                    _("Unsupported report type %s found.", report.report_type)
                )
            rendered[res_id] = render_res
        return rendered

    def _get_report_streams_batch(
        self, report: IrActionsReport, res_ids: list[int]
    ) -> dict | None:
        if len(res_ids) < 2 or report.attachment:
            return None
        IrActionsReport = self.env["ir.actions.report"]
        collected, report_type = IrActionsReport._pre_render_qweb_pdf(
            report, res_ids=list(res_ids)
        )
        if report_type != "pdf":
            return None
        streams = {}
        for res_id in res_ids:
            stream = (collected.get(res_id) or {}).get("stream")
            if not stream:
                return None
            streams[res_id] = stream
        return streams

    def _prepare_attachment_vals(
        self,
        res_ids: list[int],
        render_fields: Collection[str],
        render_results: dict | None = None,
    ) -> dict:
        self.ensure_one()
        if render_results is None:
            render_results = {}
        res_ids = list(res_ids)
        render_fields = set(render_fields)

        if "attachment_ids" in render_fields:
            for res_id in res_ids:
                render_results.setdefault(res_id, {})["attachment_ids"] = (
                    self.attachment_ids.ids
                )

        if "report_template_ids" in render_fields and res_ids:
            records_by_id = {}
            if self.report_template_ids:
                records_by_id = {
                    record.id: record for record in self._get_records(res_ids)
                }
            for res_id in res_ids:
                render_results.setdefault(res_id, {}).setdefault("attachments", [])
            for report in self.report_template_ids:
                rendered = self._render_report_per_record(report, res_ids)
                for res_id, (report_content, report_format) in rendered.items():
                    report_name = self._get_report_attachment_name(
                        report, records_by_id[res_id], report_format
                    )
                    render_results[res_id]["attachments"].append(
                        (report_name, base64.b64encode(report_content))
                    )

        if render_fields & ATTACHMENT_FIELD_NAMES and self._is_thread_model():
            records_attachments = self._get_records(
                res_ids
            )._process_attachments_for_template_post(self)
            for res_id, additional_attachments in records_attachments.items():
                if not additional_attachments:
                    continue
                values = render_results.setdefault(res_id, {})
                if additional_attachments.get("attachment_ids"):
                    values.setdefault("attachment_ids", []).extend(
                        additional_attachments["attachment_ids"]
                    )
                if additional_attachments.get("attachments"):
                    values.setdefault("attachments", []).extend(
                        additional_attachments["attachments"]
                    )

        return render_results

    def _get_report_attachment_name(
        self, report: IrActionsReport, record: models.BaseModel, report_format: str
    ) -> str:
        name = ""
        if report.print_report_name:
            name = safe_eval(report.print_report_name, {"object": record, "time": time})
        name = str(name or "") or _("Report - %(report_name)s", report_name=report.name)
        extension = "." + report_format
        return name if name.endswith(extension) else name + extension

    def _prepare_recipient_vals(
        self,
        res_ids: list[int],
        render_fields: Collection[str],
        allow_suggested: bool = False,
        find_or_create_partners: bool = False,
        render_results: dict | None = None,
    ) -> dict:
        self.ensure_one()
        if render_results is None:
            render_results = {}
        res_ids = list(res_ids)
        render_fields = set(render_fields)

        if self.use_default_to and self.model:
            if allow_suggested:
                suggested_recipients = self._get_records(
                    res_ids
                )._message_get_suggested_recipients_batch(
                    reply_discussion=True,
                    no_create=not find_or_create_partners,
                )
                for res_id, suggested_list in suggested_recipients.items():
                    pids = [r["partner_id"] for r in suggested_list if r["partner_id"]]
                    email_to_lst = [
                        tools.mail.formataddr((r["name"] or "", r["email"] or ""))
                        for r in suggested_list
                        if not r["partner_id"]
                    ]
                    render_results.setdefault(res_id, {})
                    render_results[res_id]["partner_ids"] = pids
                    render_results[res_id]["email_to"] = ", ".join(email_to_lst)
            else:
                default_recipients = self._get_records(
                    res_ids
                )._message_get_default_recipients()
                for res_id, recipients in default_recipients.items():
                    render_results.setdefault(res_id, {}).update(recipients)
        else:
            for field in RECIPIENT_FIELD_NAMES & render_fields:
                generated_field_values = self._render_field(field, res_ids)
                for res_id in res_ids:
                    render_results.setdefault(res_id, {})[field] = (
                        generated_field_values[res_id]
                    )

        if find_or_create_partners:
            records_emails = {}
            for record in self._get_records(res_ids):
                record_values = render_results.setdefault(record.id, {})
                mails = tools.email_split(
                    record_values.pop("email_to", "")
                ) + tools.email_split(record_values.pop("email_cc", ""))
                records_emails[record] = mails

            if self._is_thread_model():
                finder = self._get_records(res_ids)
            else:
                finder = self.env["mail.thread"]
            records_partners = finder._partner_find_from_emails(records_emails)
            for res_id, partners in records_partners.items():
                render_results.setdefault(res_id, {}).setdefault(
                    "partner_ids", []
                ).extend(partners.ids)

        parsed_partner_to = {}
        for res_id in res_ids:
            partner_to = render_results.get(res_id, {}).pop("partner_to", "")
            if partner_to:
                parsed_partner_to[res_id] = self._parse_partner_to(partner_to)
        if parsed_partner_to:
            all_partner_to = set().union(*parsed_partner_to.values())
            existing_pids = set(
                self.env["res.partner"].sudo().browse(list(all_partner_to)).exists().ids
            )
            for res_id, pids in parsed_partner_to.items():
                render_results[res_id].setdefault("partner_ids", []).extend(
                    set(pids) & existing_pids
                )

        return render_results

    def _prepare_scheduled_date_vals(
        self, res_ids: list[int], render_results: dict | None = None
    ) -> dict:
        self.ensure_one()
        if render_results is None:
            render_results = {}

        scheduled_dates = self._render_field("scheduled_date", res_ids)
        for res_id in res_ids:
            scheduled_date = self._process_scheduled_date(scheduled_dates.get(res_id))
            render_results.setdefault(res_id, {})["scheduled_date"] = scheduled_date

        return render_results

    def _prepare_static_vals(
        self,
        res_ids: list[int],
        render_fields: Collection[str],
        render_results: dict | None = None,
    ) -> dict:
        self.ensure_one()
        if render_results is None:
            render_results = {}

        for res_id in res_ids:
            values = render_results.setdefault(res_id, {})

            if "auto_delete" in render_fields:
                values["auto_delete"] = self.auto_delete
            if "email_layout_xmlid" in render_fields:
                values["email_layout_xmlid"] = self.email_layout_xmlid
            if "mail_server_id" in render_fields:
                values["mail_server_id"] = self.mail_server_id.id
            if "model" in render_fields:
                values["model"] = self.model
            if "res_id" in render_fields:
                values["res_id"] = res_id or False

        return render_results

    def _prepare_mail_vals(
        self,
        res_ids: list[int],
        render_fields: Collection[str],
        recipients_allow_suggested: bool = False,
        find_or_create_partners: bool = False,
    ) -> dict:
        self.ensure_one()
        self._check_has_model()
        render_fields_set = set(render_fields)
        fields_torender = render_fields_set - TEMPLATE_SPECIFIC_FIELD_NAMES

        render_results = {}
        for template, template_res_ids in self._classify_per_lang(res_ids).values():
            for field in fields_torender:
                generated_field_values = template._render_field(field, template_res_ids)
                for res_id, field_value in generated_field_values.items():
                    render_results.setdefault(res_id, {})[field] = field_value

            if render_fields_set & RECIPIENT_FIELD_NAMES:
                template._prepare_recipient_vals(
                    template_res_ids,
                    render_fields_set,
                    render_results=render_results,
                    allow_suggested=recipients_allow_suggested,
                    find_or_create_partners=find_or_create_partners,
                )

            if "scheduled_date" in render_fields_set:
                template._prepare_scheduled_date_vals(
                    template_res_ids, render_results=render_results
                )

            template._prepare_static_vals(
                template_res_ids, render_fields_set, render_results=render_results
            )

            if render_fields_set & ATTACHMENT_FIELD_NAMES:
                template._prepare_attachment_vals(
                    template_res_ids, render_fields_set, render_results=render_results
                )

        return render_results

    @classmethod
    def _parse_partner_to(cls, partner_to: Any) -> list[int]:
        try:
            parsed = literal_eval(partner_to or "[]")
        except ValueError, SyntaxError, TypeError, MemoryError, RecursionError:
            parsed = str(partner_to).split(",")
        if not isinstance(parsed, (list, tuple, set)):
            parsed = [parsed]
        partner_ids = []
        for pid in parsed:
            if isinstance(pid, str):
                if pid.strip().isdigit():
                    partner_ids.append(int(pid.strip()))
            elif isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                partner_ids.append(pid)
        return partner_ids

    def _get_model(self) -> models.Model:
        self._check_has_model()
        return self.env[self.model]

    def _get_records(self, res_ids: Collection[int]) -> models.Model:
        return self._get_model().browse(res_ids)

    def _is_thread_model(self) -> bool:
        return self.model and isinstance(self.env[self.model], self.pool["mail.thread"])

    def _check_has_model(self) -> None:
        if not self.model:
            raise UserError(
                _(
                    "Mail template %(template_name)s has no target model, so it cannot "
                    "be rendered or sent.",
                    template_name=self.display_name,
                )
            )

    def _send_check_access(self, res_ids: list[int]) -> None:
        self._get_records(res_ids).check_access("read")

    def send_mail(
        self,
        res_id: int,
        force_send: bool = False,
        raise_exception: bool = False,
        email_values: dict | None = None,
        email_layout_xmlid: str | Literal[False] = False,
    ) -> int:
        self.ensure_one()
        return self.send_mail_batch(
            [res_id],
            force_send=force_send,
            raise_exception=raise_exception,
            email_values=email_values,
            email_layout_xmlid=email_layout_xmlid,
        )[0].id

    def send_mail_batch(
        self,
        res_ids: list[int],
        force_send: bool = False,
        raise_exception: bool = False,
        email_values: dict | None = None,
        email_layout_xmlid: str | Literal[False] = False,
    ) -> MailMail:
        self.ensure_one()
        self._send_check_access(res_ids)
        sending_email_layout_xmlid = email_layout_xmlid or self.email_layout_xmlid

        mails_sudo = self.env["mail.mail"].sudo()
        batch_size = self._get_mail_batch_size()
        RecordModel = self._get_model()
        record_ir_model = self.env["ir.model"]._get(self.model)

        for res_ids_chunk in batched(res_ids, batch_size, strict=False):
            res_ids_values = self._prepare_mail_vals(
                res_ids_chunk,
                (
                    "attachment_ids",
                    "auto_delete",
                    "body_html",
                    "email_cc",
                    "email_from",
                    "email_to",
                    "mail_server_id",
                    "model",
                    "partner_to",
                    "reply_to",
                    "report_template_ids",
                    "res_id",
                    "scheduled_date",
                    "subject",
                ),
            )
            values_list = [res_ids_values[res_id] for res_id in res_ids_chunk]

            records = RecordModel.browse(res_ids_chunk)
            attachments_list = []

            res_ids_langs, res_ids_companies = {}, {}
            if sending_email_layout_xmlid:
                res_ids_langs = self._render_lang(list(res_ids_chunk))
                res_ids_companies = records._mail_get_companies(
                    default=self.env.company
                )

            for record in records:
                values = res_ids_values[record.id]
                values["recipient_ids"] = [
                    Command.link(pid) for pid in (values.pop("partner_ids", None) or [])
                ]
                values["attachment_ids"] = [
                    Command.link(aid) for aid in (values.get("attachment_ids") or [])
                ]
                values.update(email_values or {})

                attachments_list.append(values.pop("attachments", []))

                if "email_from" in values and not values.get("email_from"):
                    values.pop("email_from")

                if not sending_email_layout_xmlid:
                    values["body"] = values["body_html"]
                    continue

                lang = res_ids_langs.get(record.id) or self.env.lang
                company = res_ids_companies.get(record.id) or self.env.company
                model_lang = record_ir_model.with_context(lang=lang)
                self_lang = self.with_context(lang=lang)
                record_lang = record.with_context(lang=lang)

                values["body_html"] = self_lang._render_encapsulate(
                    sending_email_layout_xmlid,
                    values["body_html"],
                    add_context={
                        "company": company,
                        "model_description": model_lang.display_name,
                    },
                    context_record=record_lang,
                )
                values["body"] = values["body_html"]

            mails = self.env["mail.mail"].sudo().create(values_list)

            for mail, attachments in zip(mails, attachments_list, strict=True):
                if attachments:
                    attachments_values = [
                        Command.create(
                            {
                                "name": name,
                                "datas": datas,
                                "type": "binary",
                                "res_model": "mail.message",
                                "res_id": mail.mail_message_id.id,
                            }
                        )
                        for (name, datas) in attachments
                    ]
                    mail.with_context(default_type=None).write(
                        {"attachment_ids": attachments_values}
                    )

            mails_sudo += mails

        if force_send:
            mails_sudo.send(raise_exception=raise_exception)
        return mails_sudo

    def _has_unsafe_expression_template_qweb(
        self, template_src: str, model: str, fname: str | None = None
    ) -> bool:
        if self._expression_is_default(template_src, model, fname):
            return False
        return super()._has_unsafe_expression_template_qweb(
            template_src, model, fname=fname
        )

    def _has_unsafe_expression_template_inline_template(
        self, template_txt: str, model: str, fname: str | None = None
    ) -> bool:
        if self._expression_is_default(template_txt, model, fname):
            return False
        return super()._has_unsafe_expression_template_inline_template(
            template_txt, model, fname=fname
        )

    def _expression_is_default(
        self, source: str, model: str, fname: str | None
    ) -> bool:
        if not fname or not model:
            return False
        return source == self._get_model_template_defaults(model).get(fname)

    @api.model
    def _get_model_template_defaults(self, model: str) -> dict:
        defaults = getattr(self.env[model], "_mail_template_default_values", None)
        return (defaults and defaults()) or {}
