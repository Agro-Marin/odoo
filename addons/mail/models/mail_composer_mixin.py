import typing

from odoo import _, api, fields, models, tools

from .mail_render_mixin import BYPASS_RESTRICTED_RENDERING

if typing.TYPE_CHECKING:
    from .mail_template import MailTemplate


class MailComposerMixin(models.AbstractModel):
    _name = "mail.composer.mixin"
    _inherit = ["mail.render.mixin"]
    _description = "Mail Composer Mixin"

    subject = fields.Char(
        "Subject",
        compute="_compute_subject",
        readonly=False,
        store=True,
        compute_sudo=False,
    )
    body = fields.Html(
        "Contents",
        compute="_compute_body",
        readonly=False,
        store=True,
        compute_sudo=False,
        render_engine="qweb",
        render_options={"post_process": True},
        sanitize="email_outgoing",
    )
    body_has_template_value = fields.Boolean(
        "Body content is the same as the template",
        compute="_compute_body_has_template_value",
    )
    template_id: MailTemplate = fields.Many2one(
        "mail.template", "Mail Template", domain="[('model', '=', render_model)]"
    )
    lang = fields.Char(
        compute="_compute_lang",
        precompute=True,
        readonly=False,
        store=True,
        compute_sudo=False,
    )
    is_mail_template_editor = fields.Boolean(
        "Is Editor", compute="_compute_is_mail_template_editor"
    )
    can_edit_body = fields.Boolean("Can Edit Body", compute="_compute_can_edit_body")

    @api.depends("template_id")
    def _compute_subject(self) -> None:
        for composer_mixin in self:
            if composer_mixin.template_id.subject:
                composer_mixin.subject = composer_mixin.template_id.subject
            elif not composer_mixin.template_id:
                composer_mixin.subject = False

    @api.depends("template_id")
    def _compute_body(self) -> None:
        for composer_mixin in self:
            if not tools.is_html_empty(composer_mixin.template_id.body_html):
                composer_mixin.body = composer_mixin.template_id.body_html
            elif not composer_mixin.template_id:
                composer_mixin.body = False

    @api.depends("body", "template_id")
    def _compute_body_has_template_value(self) -> None:
        for composer_mixin in self:
            if (
                not tools.is_html_empty(composer_mixin.body)
                and composer_mixin.template_id
            ):
                template_value = composer_mixin.template_id.body_html
                sanitize_vals = {
                    "output_method": "xml",
                    "sanitize_attributes": False,
                    "sanitize_conditional_comments": False,
                    "sanitize_form": True,
                    "sanitize_style": True,
                    "sanitize_tags": False,
                    "silent": True,
                    "strip_classes": False,
                    "strip_style": False,
                }
                sanitized_template_value = tools.html_sanitize(
                    template_value, **sanitize_vals
                )
                composer_mixin.body_has_template_value = composer_mixin.body in (
                    template_value,
                    sanitized_template_value,
                )
            else:
                composer_mixin.body_has_template_value = False

    @api.depends("template_id")
    def _compute_lang(self) -> None:
        for composer_mixin in self:
            if composer_mixin.template_id.lang:
                composer_mixin.lang = composer_mixin.template_id.lang
            elif not composer_mixin.template_id:
                composer_mixin.lang = False

    @api.depends_context("uid")
    def _compute_is_mail_template_editor(self) -> None:
        is_mail_template_editor = self.env.is_admin() or self.env.user.has_group(
            "mail.group_mail_template_editor"
        )
        for record in self:
            record.is_mail_template_editor = is_mail_template_editor

    @api.depends("template_id", "is_mail_template_editor")
    def _compute_can_edit_body(self) -> None:
        for record in self:
            record.can_edit_body = (
                record.is_mail_template_editor or not record.template_id
            )

    def _render_lang(self, res_ids: list[int], engine: str = "inline_template") -> dict:
        if not self.template_id:
            return super()._render_lang(res_ids, engine=engine)

        composer_value = self.lang
        template_value = self.template_id.lang

        bypass = False
        equality = composer_value == template_value or (
            not composer_value and not template_value
        )
        if not self.is_mail_template_editor and equality:
            bypass = True

        record = (
            self.with_context(bypass_restricted_rendering=BYPASS_RESTRICTED_RENDERING)
            if bypass
            else self
        )
        return super(MailComposerMixin, record)._render_lang(res_ids, engine=engine)

    def _render_field(self, field: str, res_ids: list[int], *args, **kwargs) -> dict:
        if field not in self:
            raise ValueError(
                _(
                    "Rendering of %(field_name)s is not possible as not defined on template.",
                    field_name=field,
                )
            )

        if not self.template_id:
            return super()._render_field(field, res_ids, *args, **kwargs)

        template_field = {
            "body": "body_html",
        }.get(field, field)
        if template_field not in self.template_id:
            raise ValueError(
                _(
                    "Rendering of %(field_name)s is not possible as no counterpart on template.",
                    field_name=field,
                )
            )

        composer_value = self[field]
        template_value = self.template_id[template_field]
        translation_asked = kwargs.get("compute_lang") or kwargs.get("set_lang")
        equality = (
            self.body_has_template_value
            if field == "body"
            else composer_value == template_value
        )

        call_sudo = False
        if (
            not self.is_mail_template_editor
            and field == "body"
            and (not self.can_edit_body or self.body_has_template_value)
        ):
            call_sudo = True
            self.body = self.template_id.body_html
        if (
            not self.is_mail_template_editor
            and field != "body"
            and composer_value == template_value
        ):
            call_sudo = True

        if translation_asked and equality:
            if not kwargs.get("res_ids_lang"):
                kwargs["res_ids_lang"] = self._render_lang(res_ids)
            template = (
                self.template_id.with_context(
                    bypass_restricted_rendering=BYPASS_RESTRICTED_RENDERING
                )
                if call_sudo
                else self.template_id
            )
            return template._render_field(
                template_field,
                res_ids,
                *args,
                **kwargs,
            )

        record = (
            self.with_context(bypass_restricted_rendering=BYPASS_RESTRICTED_RENDERING)
            if call_sudo
            else self
        )
        return super(MailComposerMixin, record)._render_field(
            field, res_ids, *args, **kwargs
        )
