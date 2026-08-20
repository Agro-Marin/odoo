import typing
from collections.abc import Callable

from odoo import api, fields, models, tools

from .mixin_mail_render import BYPASS_RESTRICTED_RENDERING

if typing.TYPE_CHECKING:
    from .mail_template import MailTemplate


class MixinMailComposer(models.AbstractModel):
    _name = "mixin.mail.composer"
    _inherit = ["mixin.mail.render"]
    _description = "Mail Composer Mixin"

    _template_field_counterparts = {"body": "body_html"}

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

    def _copy_from_template(
        self, field: str, is_empty: Callable[[typing.Any], bool] | None = None
    ) -> None:
        template_field = self._get_template_field(field)
        for record in self:
            if not record.template_id:
                record[field] = False
                continue
            value = record.template_id[template_field]
            if not (is_empty(value) if is_empty else not value):
                record[field] = value

    @api.depends("template_id")
    def _compute_subject(self) -> None:
        self._copy_from_template("subject")

    @api.depends("template_id")
    def _compute_body(self) -> None:
        self._copy_from_template("body", is_empty=tools.is_html_empty)

    @api.depends("template_id")
    def _compute_lang(self) -> None:
        self._copy_from_template("lang")

    @api.depends("body", "template_id")
    def _compute_body_has_template_value(self) -> None:
        for composer_mixin in self:
            composer_mixin.body_has_template_value = bool(
                composer_mixin.template_id
                and not tools.is_html_empty(composer_mixin.body)
                and composer_mixin.body == composer_mixin.template_id.body_html
            )

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

    def _get_template_field(self, field: str) -> str:
        if field not in self._fields:
            raise ValueError(f"{self._name} has no field {field!r} to render")
        template_field = self._template_field_counterparts.get(field, field)
        if template_field not in self.env["mail.template"]._fields:
            raise ValueError(
                f"{self._name}.{field} has no counterpart on mail.template"
            )
        return template_field

    def _is_value_from_template(self, field: str) -> bool:
        self.ensure_one()
        if not self.template_id:
            return False
        if field == "body":
            return self.body_has_template_value
        value = self[field]
        template_value = self.template_id[self._get_template_field(field)]
        return value == template_value or not (value or template_value)

    def _must_render_template_value(self, field: str) -> bool:
        self.ensure_one()
        return (
            field == "body"
            and not self.is_mail_template_editor
            and not self.can_edit_body
        )

    def _render_lang(self, res_ids: list[int], engine: str = "inline_template") -> dict:
        self.ensure_one()
        record = self
        if self._is_value_from_template("lang") and not self.is_mail_template_editor:
            record = self.with_context(
                bypass_restricted_rendering=BYPASS_RESTRICTED_RENDERING
            )
        return super(MixinMailComposer, record)._render_lang(res_ids, engine=engine)

    def _render_field(
        self,
        field: str,
        res_ids: list[int],
        engine: str = "inline_template",
        compute_lang: bool = False,
        res_ids_lang: dict[int, str] | typing.Literal[False] = False,
        set_lang: str | typing.Literal[False] = False,
        add_context: dict | None = None,
        options: dict | None = None,
    ) -> dict:
        self.ensure_one()
        if not self.template_id:
            return super()._render_field(
                field,
                res_ids,
                engine=engine,
                compute_lang=compute_lang,
                res_ids_lang=res_ids_lang,
                set_lang=set_lang,
                add_context=add_context,
                options=options,
            )

        template_field = self._get_template_field(field)
        from_template = self._is_value_from_template(field)
        translation_asked = bool(compute_lang or set_lang)

        if self._must_render_template_value(field) or (
            translation_asked and from_template
        ):
            if translation_asked and not res_ids_lang and not set_lang:
                res_ids_lang = self._get_res_ids_lang(res_ids)
            return self.template_id._render_field(
                template_field,
                res_ids,
                engine=engine,
                compute_lang=compute_lang,
                res_ids_lang=res_ids_lang,
                set_lang=set_lang,
                add_context=add_context,
                options=options,
            )

        record = self
        if from_template and not self.is_mail_template_editor:
            record = self.with_context(
                bypass_restricted_rendering=BYPASS_RESTRICTED_RENDERING
            )
        return super(MixinMailComposer, record)._render_field(
            field,
            res_ids,
            engine=engine,
            compute_lang=compute_lang,
            res_ids_lang=res_ids_lang,
            set_lang=set_lang,
            add_context=add_context,
            options=options,
        )
