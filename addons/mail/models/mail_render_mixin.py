import copy
import datetime
import logging
import re
import typing
from collections.abc import Callable
from typing import Any, Literal, Self

import babel
from lxml import etree, html
from markupsafe import Markup

from odoo import _, api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, UserError
from odoo.libs.web import urls
from odoo.tools.mail import is_html_empty, prepend_html_content
from odoo.tools.rendering_tools import (
    QWebError,
    convert_inline_template_to_qweb,
    parse_inline_template,
    render_inline_template,
    renders_as_no_value,
    template_env_globals,
)

if typing.TYPE_CHECKING:
    from odoo.api import Environment

_logger = logging.getLogger(__name__)

BYPASS_RESTRICTED_RENDERING = object()

TEMPLATE_FIELD_TYPES = ("char", "text", "html")

LOCAL_LINK_PATTERNS = (
    re.compile(r"""(<(?:img|v:fill|v:image)(?=\s)[^>]*\ssrc=")(/[^/][^"]+)"""),
    re.compile(r"""(<a(?=\s)[^>]*\shref=")(/[^/][^"]+)"""),
    re.compile(r"""(<[\w-]+(?=\s)[^>]*\sbackground=")(/[^/][^"]+)"""),
    re.compile(
        r"""(                            # 1: the element up to the url, opening quote included
            <[^>]+\bstyle=['"]           # an element carrying a style attribute
            [^'"]+\burl\(                # whose style contains url(
            (?:&\#34;|'|&quot;|&\#39;|")?  # the url may open with an (escaped) quote
        )(                               # 2: the url itself
            /[^/][^'")]*                 # a local path; "//host" is not one
        )""",
        re.VERBOSE,
    ),
)


def format_date(
    env: Environment,
    date: datetime.datetime | datetime.date | str,
    pattern: str | Literal[False] = False,
    lang_code: str | Literal[False] = False,
) -> str | datetime.datetime | datetime.date:
    try:
        return tools.format_date(env, date, date_format=pattern, lang_code=lang_code)
    except babel.core.UnknownLocaleError:
        return date


def format_datetime(
    env: Environment,
    dt: datetime.datetime | str,
    tz: str | Literal[False] = False,
    dt_format: str | Literal[False] = "medium",
    lang_code: str | Literal[False] = False,
) -> str | datetime.datetime:
    try:
        return tools.format_datetime(
            env, dt, tz=tz, dt_format=dt_format, lang_code=lang_code
        )
    except babel.core.UnknownLocaleError:
        return dt


def format_time(
    env: Environment,
    time: datetime.time | datetime.datetime | str,
    tz: str | Literal[False] = False,
    time_format: str | Literal[False] = "medium",
    lang_code: str | Literal[False] = False,
) -> str | datetime.time | datetime.datetime:
    try:
        return tools.format_time(
            env, time, tz=tz, time_format=time_format, lang_code=lang_code
        )
    except babel.core.UnknownLocaleError:
        return time


class MailRenderMixin(models.AbstractModel):
    _name = "mail.render.mixin"
    _description = "Mail Render Mixin"

    _unrestricted_rendering = False

    lang = fields.Char(
        "Language",
        help="Optional translation language (ISO code) to select when sending out an email. "
        "If not set, the main partner's language will be used. This should usually be a placeholder expression "
        "that provides the appropriate language, e.g. {{ object.partner_id.lang }}.",
    )
    render_model = fields.Char(
        "Rendering Model", compute="_compute_render_model", store=False
    )

    def _compute_render_model(self) -> None:
        self.render_model = False

    @api.model
    def _get_mail_batch_size(self, default: int = 50) -> int:
        batch_size = self.env["ir.config_parameter"]._get_int_param(
            "mail.batch_size", 0
        )
        if batch_size < 0:
            _logger.warning(
                "Negative ICP 'mail.batch_size' (%s), falling back to default %s",
                batch_size,
                default,
            )
            batch_size = 0
        return batch_size or default

    def _valid_field_parameter(self, field: fields.Field, name: str) -> bool:
        return name in [
            "render_engine",
            "render_options",
        ] or super()._valid_field_parameter(field, name)

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        records = super().create(vals_list)
        if self._unrestricted_rendering:
            records._check_access_right_dynamic_template()
        return records

    def write(self, vals: ValuesType) -> Literal[True]:
        result = super().write(vals)
        if self._unrestricted_rendering and (
            vals.keys() & self._get_dynamic_field_names()
        ):
            self._check_access_right_dynamic_template()
        return result

    def _update_field_translations(
        self,
        field_name: str,
        translations: dict[str, str | Literal[False] | dict[str, str]],
        digest: Callable[[str], str] | None = None,
        source_lang: str = "",
    ) -> bool:
        res = super()._update_field_translations(
            field_name, translations, digest=digest, source_lang=source_lang
        )
        if self._unrestricted_rendering and field_name in (
            self._get_dynamic_field_names()
        ):
            for lang in translations:
                self.with_context(lang=lang)._check_access_right_dynamic_template(
                    fnames={field_name}
                )
        return res

    def _replace_local_links(
        self, html_content: str, base_url: str | None = None
    ) -> str:
        if not html_content:
            return html_content

        assert isinstance(html_content, str)
        wrapper = html_content.__class__

        def to_absolute(match: re.Match[str]) -> str:
            nonlocal base_url
            if not base_url:
                base_url = (
                    self.env["ir.config_parameter"].sudo().get_param("web.base.url")
                )
            try:
                return match.group(1) + urls.urljoin(base_url, match.group(2))
            except ValueError:
                return match.group(0)

        for pattern in LOCAL_LINK_PATTERNS:
            html_content = pattern.sub(to_absolute, html_content)

        return wrapper(html_content)

    @api.model
    def _render_encapsulate(
        self,
        layout_xmlid: str,
        html_content: str,
        add_context: dict | None = None,
        context_record: models.BaseModel | None = None,
    ) -> Markup:
        add_context = add_context or {}
        record_name = add_context.get("record_name")
        if record_name is None:
            record_name = context_record.display_name if context_record else ""
        subtype = add_context.get("subtype", self.env["mail.message.subtype"].sudo())
        template_ctx = {
            "body": html_content,
            "record": context_record,
            "record_name": record_name,
            **add_context,
        }
        if not template_ctx.get("message"):
            msg_vals = {"body": html_content}
            if context_record:
                msg_vals.update(
                    {"model": context_record._name, "res_id": context_record.id}
                )
            template_ctx["message"] = self.env["mail.message"].sudo().new(msg_vals)
        if not subtype:
            template_ctx["is_discussion"] = False
            template_ctx["subtype_internal"] = False
        else:
            if "is_discussion" not in template_ctx:
                template_ctx["is_discussion"] = subtype.id == self.env[
                    "ir.model.data"
                ]._xmlid_to_res_id("mail.mt_comment")
            if "subtype_internal" not in template_ctx:
                template_ctx["subtype_internal"] = subtype.is_internal
        template_ctx.setdefault("subtype", subtype)
        template_ctx.setdefault("tracking_values", [])
        if "model_description" not in template_ctx:
            template_ctx["model_description"] = (
                self.env["ir.model"]._get(context_record._name).display_name
                if context_record
                else False
            )
        template_ctx.setdefault("subtitles", [record_name])
        template_ctx.setdefault("author_user", False)
        if "company" not in template_ctx:
            template_ctx["company"] = (
                context_record._mail_get_companies(default=self.env.company)[
                    context_record.id
                ]
                if context_record
                else self.env.company
            )
        template_ctx.setdefault("email_add_signature", False)
        template_ctx.setdefault("lang", self.env.lang)
        template_ctx.setdefault("signature", "")
        template_ctx.setdefault("show_unfollow", False)
        template_ctx.setdefault("website_url", "")
        template_ctx.setdefault("button_access", False)
        template_ctx.setdefault("has_button_access", False)
        template_ctx.setdefault(
            "email_notification_force_header",
            self.env.context.get("email_notification_force_header", False),
        )
        template_ctx.setdefault(
            "email_notification_force_footer",
            self.env.context.get("email_notification_force_footer", False),
        )
        template_ctx.setdefault(
            "email_notification_allow_header",
            self.env.context.get("email_notification_allow_header", True),
        )
        template_ctx.setdefault(
            "email_notification_allow_footer",
            self.env.context.get("email_notification_allow_footer", False),
        )
        template_ctx.setdefault("is_html_empty", is_html_empty)

        rendered = self.env["ir.qweb"]._render(
            layout_xmlid, template_ctx, minimal_qcontext=True, raise_if_not_found=False
        )
        if not rendered:
            _logger.warning(
                "QWeb template %s not found when rendering encapsulation template.",
                layout_xmlid,
            )
            return Markup()
        return self.env["mail.render.mixin"]._replace_local_links(rendered)

    @api.model
    def _prepend_preview(self, html_content: str, preview: str | Literal[False]) -> str:
        preview = preview.strip() if preview else preview
        if not preview:
            return html_content

        html_preview = Markup("""
                <div style="display:none;font-size:1px;height:0px;width:0px;opacity:0;">
                    {}
                </div>
            """).format(convert_inline_template_to_qweb(preview))
        return prepend_html_content(html_content, html_preview)

    def _is_restricted(self) -> bool:
        return (
            not self._unrestricted_rendering
            and self.env.context.get("bypass_restricted_rendering")
            is not BYPASS_RESTRICTED_RENDERING
            and not self.env.is_admin()
            and not self.env.user.has_group("mail.group_mail_template_editor")
        )

    def _get_dynamic_field_names(self) -> set:
        return {
            fname
            for fname, field in self._fields.items()
            if field.type in TEMPLATE_FIELD_TYPES and field.store
        }

    def _has_unsafe_expression(self, fnames: set | None = None) -> bool:
        for template in self.sudo():
            scanned = template._get_dynamic_field_names()
            if fnames is not None:
                scanned &= fnames
            for fname in scanned:
                field = template._fields[fname]
                engine = getattr(field, "render_engine", "inline_template")
                if engine in ("qweb", "qweb_view"):
                    if self._has_unsafe_expression_template_qweb(
                        template[fname], template.render_model, fname
                    ):
                        return True
                elif self._has_unsafe_expression_template_inline_template(
                    template[fname], template.render_model, fname
                ):
                    return True
        return False

    @api.model
    def _has_unsafe_expression_template_qweb(
        self, template_src: str, model: str, fname: str | None = None
    ) -> bool:
        if template_src:
            try:
                node = self._get_qweb_template_node(str(template_src))[0]
                self.env["ir.qweb"].with_context(
                    raise_on_forbidden_code_for_model=model
                )._generate_code(node)
            except PermissionError:
                return True
        return False

    @api.model
    def _has_unsafe_expression_template_inline_template(
        self, template_txt: str, model: str, fname: str | None = None
    ) -> bool:
        if template_txt:
            template_instructions = parse_inline_template(str(template_txt))
            expressions = [inst[1] for inst in template_instructions]
            if not all(self._is_static_expression(e, model) for e in expressions if e):
                return True
        return False

    def _check_access_right_dynamic_template(self, fnames: set | None = None) -> None:
        if (
            not self.env.su
            and not self.env.user.has_group("mail.group_mail_template_editor")
            and self._has_unsafe_expression(fnames=fnames)
        ):
            raise AccessError(self._prepare_template_editor_error())

    def _prepare_template_editor_error(self) -> str:
        group = self.env.ref("mail.group_mail_template_editor")
        return _(
            "Only members of %(group_name)s group are allowed to edit templates containing sensible placeholders",
            group_name=group.name,
        )

    @api.model
    def _render_eval_context(self) -> dict:
        render_context = dict(template_env_globals)
        render_context.update(
            {
                "ctx": self.env.context,
                "format_addr": tools.formataddr,
                "format_date": lambda date, date_format=False, lang_code=False: (
                    format_date(self.env, date, date_format, lang_code)
                ),
                "format_datetime": lambda dt, tz=False, dt_format=False, lang_code=False: (
                    format_datetime(self.env, dt, tz, dt_format, lang_code)
                ),
                "format_time": lambda time, tz=False, time_format=False, lang_code=False: (
                    format_time(self.env, time, tz, time_format, lang_code)
                ),
                "format_amount": lambda amount, currency, lang_code=False: (
                    tools.format_amount(self.env, amount, currency, lang_code)
                ),
                "format_duration": tools.format_duration,
                "is_html_empty": is_html_empty,
                "slug": self.env["ir.http"]._slug,
                "user": self.env.user,
                "env": self.env,
            }
        )
        return render_context

    @api.model
    @tools.ormcache("template_src", cache="templates")
    def _get_qweb_template_node(self, template_src: str) -> tuple:
        return (html.fragment_fromstring(template_src, create_parent="div"), {})

    @api.model
    def _render_template_qweb(
        self,
        template_src: str,
        model: str,
        res_ids: list[int],
        add_context: dict | None = None,
        options: dict | None = None,
    ) -> dict:
        results = dict.fromkeys(res_ids, Markup())
        if not template_src or not res_ids:
            return results

        if not self._has_unsafe_expression_template_qweb(template_src, model):
            return self._render_template_qweb_static(
                template_src, model, res_ids, options=options
            )

        variables = self._render_eval_context()
        if add_context:
            variables.update(**add_context)

        options = dict(options or {})
        if self._is_restricted():
            options["raise_on_forbidden_code_for_model"] = model

        template_node, compiled_cache = self._get_qweb_template_node(str(template_src))
        qweb = self.env["ir.qweb"].with_context(__qweb_compiled_cache=compiled_cache)
        for record in self.env[model].browse(res_ids):
            variables["object"] = record
            try:
                render_result = qweb._render(template_node, variables, **options)
                render_result = render_result.removeprefix("<div>").removesuffix(
                    "</div>"
                )
            except Exception as error:
                self._check_render_error(error, template_src, model)
            results[record.id] = render_result

        return results

    def _check_render_error(
        self, error: Exception, template_src: str, model: str
    ) -> typing.NoReturn:
        if isinstance(error, QWebError) and isinstance(
            error.__cause__, PermissionError
        ):
            raise AccessError(self._prepare_template_editor_error()) from error
        if isinstance(error, AccessError):
            raise error
        if isinstance(error, QWebError) and isinstance(error.__cause__, AccessError):
            raise error.__cause__ from error

        if isinstance(error, QWebError):
            error_details = str(error).split("\nTemplate:")[0].strip()
        else:
            error_details = str(error)

        template_label, is_identified = self._get_render_error_label()
        truncated_src = template_src
        if len(template_src) > 1000:
            truncated_src = (
                f"{template_src[:500]}\n[...] (content truncated) [...]\n"
                f"{template_src[-500:]}"
            )
        lang_context = self.env.context.get(
            "lang", _("No language detected in context")
        )

        _logger.error(
            "Failed to render QWeb template for %s - Context language:%s\n"
            "Target Model: %s\nError: %s\n%s",
            template_label,
            lang_context,
            model,
            error_details,
            template_src if not is_identified else truncated_src,
        )
        _logger.debug(
            "Failed to render QWeb template for %s", template_label, exc_info=error
        )

        raise UserError(
            _(
                "Failed to render QWeb template for %(template_label)s\n"
                "Target Model: %(model_name)s\n"
                "Language context: %(lang_context)s\n"
                "Error: %(error_details)s\n\n"
                "Template Source Snippet:\n%(template_src)s",
                template_label=template_label,
                model_name=model,
                lang_context=lang_context,
                error_details=error_details,
                template_src=truncated_src,
            )
        ) from error

    def _get_render_error_label(self) -> tuple[str, bool]:
        if self._name == "mail.template" and self.id:
            return (
                _(
                    "Mail Template: '%(name)s' (ID: %(record_id)s)",
                    name=self.name or _("Unnamed Mail Template"),
                    record_id=self.id,
                ),
                True,
            )
        if (
            self._name == "mail.compose.message"
            and "mass_mailing_id" in self._fields
            and self.mass_mailing_id
        ):
            return (
                _(
                    "Mass Mailing Template: '%(name)s' (ID: %(record_id)s)",
                    name=self.mass_mailing_id.display_name or _("Unnamed Mailing"),
                    record_id=self.mass_mailing_id.id,
                ),
                True,
            )
        return _("Template name not identified"), False

    @api.model
    def _is_static_expression(self, expression: str, model: str) -> bool:
        return self.env["ir.qweb"]._is_expression_allowed(expression, model)

    @api.model
    def _resolve_static_expression(self, expression: str, record: models.Model) -> Any:
        root, *path = expression.strip().split(".")
        if root == "object":
            value = record
        elif root == "user":
            value = self.env.user
        else:
            raise SyntaxError(
                f"Unsupported root {root!r} for the static mode in {expression!r}"
            )
        for fname in path:
            value = value[fname]
        return value

    @api.model
    def _get_static_value(self, expression: str, record: models.Model) -> Any:
        try:
            value = self._resolve_static_expression(expression, record)
        except KeyError:
            return None
        if isinstance(value, models.BaseModel):
            value = value.display_name or False
        return value

    @api.model
    def _render_template_qweb_static(
        self,
        template_src: str,
        model: str,
        res_ids: list[int],
        options: dict | None = None,
    ) -> dict:
        options = options or {}
        tree = copy.deepcopy(self._get_qweb_template_node(str(template_src))[0])
        if not options.get("preserve_comments"):
            etree.strip_elements(tree, etree.Comment, with_tail=False)

        targets = [
            element
            for element in tree.iter()
            if isinstance(element.tag, str) and element.get("t-out") is not None
        ]
        for element in targets:
            expression = element.get("t-out").strip()
            if len(element) or set(element.attrib) != {"t-out"}:
                raise SyntaxError(
                    f"Unsupported t-out element for the static mode: {expression!r}"
                )
            if not self._is_static_expression(expression, model):
                raise SyntaxError(
                    f"Invalid expression for the static mode {expression!r}"
                )

        results = {}
        for record in self.env[model].browse(res_ids):
            rendered = copy.deepcopy(tree)
            for element in [
                element
                for element in rendered.iter()
                if isinstance(element.tag, str) and element.get("t-out") is not None
            ]:
                self._update_static_element(element, element.get("t-out"), record)
            results[record.id] = Markup(
                html.tostring(rendered, encoding="unicode")
                .removeprefix("<div>")
                .removesuffix("</div>")
            )
        return results

    @api.model
    def _update_static_element(
        self, element: etree._Element, expression: str, record: models.BaseModel
    ) -> None:
        value = self._get_static_value(expression, record)
        del element.attrib["t-out"]

        if value is not None and value is not False:
            element.text = None
            if isinstance(value, Markup):
                fragment = html.fragment_fromstring(str(value), create_parent="span")
                element.text = fragment.text
                element.extend(list(fragment))
            else:
                element.text = str(value)
        elif element.text:
            element.text = element.text.strip()

        if element.tag.lower() == "t":
            element.drop_tag()

    @api.model
    def _render_template_qweb_view(
        self,
        view_ref: models.BaseModel | str | int,
        model: str,
        res_ids: list[int],
        add_context: dict | None = None,
        options: dict | None = None,
    ) -> dict:
        results = {}
        if not res_ids:
            return results

        variables = self._render_eval_context()
        if add_context:
            variables.update(**add_context)

        view_ref = view_ref.id if isinstance(view_ref, models.BaseModel) else view_ref
        for record in self.env[model].browse(res_ids):
            variables["object"] = record
            try:
                results[record.id] = self.env["ir.qweb"]._render(
                    view_ref,
                    variables,
                    minimal_qcontext=True,
                    raise_if_not_found=False,
                    **(options or {}),
                )
            except Exception as error:
                _logger.info("Failed to render template: %s", view_ref, exc_info=True)
                raise UserError(
                    _(
                        "Failed to render template: %(view_ref)s\nError: %(error)s",
                        view_ref=view_ref,
                        error=str(error),
                    )
                ) from error

        return results

    @api.model
    def _render_template_inline_template(
        self,
        template_txt: str,
        model: str,
        res_ids: list[int],
        add_context: dict | None = None,
        options: dict | None = None,
    ) -> dict:
        results = dict.fromkeys(res_ids, "")
        if not template_txt or not res_ids:
            return results

        if not self._has_unsafe_expression_template_inline_template(
            str(template_txt), model
        ):
            return self._render_template_inline_template_static(
                str(template_txt), model, res_ids
            )

        if self._is_restricted():
            raise AccessError(self._prepare_template_editor_error())

        variables = self._render_eval_context()
        if add_context:
            variables.update(**add_context)

        parsed_template = parse_inline_template(str(template_txt))
        for record in self.env[model].browse(res_ids):
            variables["object"] = record

            try:
                results[record.id] = render_inline_template(
                    parsed_template, variables, format_value=_format_template_value
                )
            except Exception as error:
                _logger.info(
                    "Failed to render inline_template: \n%s",
                    template_txt,
                    exc_info=True,
                )
                raise UserError(
                    _(
                        "Failed to render inline_template template: %(template_txt)s\n"
                        "Error details: %(error)s",
                        template_txt=template_txt,
                        error=str(error),
                    )
                ) from error

        return results

    @api.model
    def _render_template_inline_template_static(
        self, template_txt: str, model: str, res_ids: list[int]
    ) -> dict:
        template = parse_inline_template(str(template_txt))
        for _string, expression, _default in template:
            if expression and not self._is_static_expression(expression, model):
                raise SyntaxError(
                    f"Invalid expression for the static mode {expression!r}"
                )

        result = {}
        for record in self.env[model].browse(res_ids):
            renderer = []
            for string, expression, default in template:
                renderer.append(string)
                if not expression:
                    continue
                value = self._get_static_value(expression, record)
                if renders_as_no_value(value):
                    value = default
                renderer.append("" if value == "" else str(value))
            result[record.id] = "".join(renderer)
        return result

    @api.model
    def _render_template_postprocess(
        self, model: str, rendered: dict[int, str]
    ) -> dict:
        res_ids = list(rendered.keys())
        return {
            res_id: self._replace_local_links(
                rendered_html,
                self.env[model].browse(res_id).with_prefetch(res_ids).get_base_url()
                if model
                else None,
            )
            for res_id, rendered_html in rendered.items()
        }

    @api.model
    def _process_scheduled_date(
        self, scheduled_date: str
    ) -> datetime.datetime | str | Literal[False]:
        if scheduled_date:
            parsed_datetime = self.env["mail.mail"]._parse_scheduled_datetime(
                scheduled_date
            )
            scheduled_date = (
                parsed_datetime.replace(tzinfo=None) if parsed_datetime else False
            )
        return scheduled_date

    @api.model
    def _render_template_get_valid_options(self) -> set:
        return {"post_process", "preserve_comments"}

    @api.model
    def _render_template(
        self,
        template_src: str,
        model: str,
        res_ids: list[int],
        engine: str = "inline_template",
        add_context: dict | None = None,
        options: dict | None = None,
    ) -> dict:
        options = options or {}

        if not isinstance(res_ids, (list, tuple)):
            raise ValueError(
                _(
                    "Template rendering should only be called with a list of IDs. Received “%(res_ids)s” instead.",
                    res_ids=res_ids,
                )
            )
        if engine not in ("inline_template", "qweb", "qweb_view"):
            raise ValueError(
                _(
                    "Template rendering supports only inline_template, qweb, or qweb_view (view or raw); received %(engine)s instead.",
                    engine=engine,
                )
            )
        valid_render_options = self._render_template_get_valid_options()
        if not options.keys() <= valid_render_options:
            raise ValueError(
                _(
                    "Those values are not supported as options when rendering: %(param_names)s",
                    param_names=", ".join(options.keys() - valid_render_options),
                )
            )

        if engine == "qweb_view":
            rendered = self._render_template_qweb_view(
                template_src, model, res_ids, add_context=add_context, options=options
            )
        elif engine == "qweb":
            rendered = self._render_template_qweb(
                template_src, model, res_ids, add_context=add_context, options=options
            )
        else:
            rendered = self._render_template_inline_template(
                template_src, model, res_ids, add_context=add_context, options=options
            )

        if options.get("post_process"):
            rendered = self._render_template_postprocess(model, rendered)

        return rendered

    def _render_lang(self, res_ids: list[int], engine: str = "inline_template") -> dict:
        self.ensure_one()
        if self.lang:
            return self._render_template(
                self.lang, self.render_model, res_ids, engine=engine
            )

        rendered_langs = dict.fromkeys(res_ids, "")
        records = self.env[self.render_model].browse(res_ids)
        customers = records._mail_get_partners()
        for record in records:
            partner = (
                customers[record.id][0]
                if customers[record.id]
                else self.env["res.partner"]
            )
            rendered_langs[record.id] = partner.lang
        return rendered_langs

    def _classify_per_lang(
        self, res_ids: list[int], engine: str = "inline_template"
    ) -> dict:
        self.ensure_one()

        if self.env.context.get("template_preview_lang"):
            lang_to_res_ids = {self.env.context["template_preview_lang"]: res_ids}
        else:
            lang_to_res_ids = {}
            for res_id, lang in self._render_lang(res_ids, engine=engine).items():
                lang_to_res_ids.setdefault(lang, []).append(res_id)

        return {
            lang: (self._with_render_lang(lang), lang_res_ids)
            for lang, lang_res_ids in lang_to_res_ids.items()
        }

    def _with_render_lang(self, lang: str | Literal[False] | None) -> Self:
        return self.with_context(lang=lang) if lang else self

    def _render_field(
        self,
        field: str,
        res_ids: list[int],
        engine: str = "inline_template",
        compute_lang: bool = False,
        res_ids_lang: dict[int, str] | Literal[False] = False,
        set_lang: str | Literal[False] = False,
        add_context: dict | None = None,
        options: dict | None = None,
    ) -> dict:
        if field not in self:
            raise ValueError(
                _(
                    "Rendering of %(field_name)s is not possible as not defined on template.",
                    field_name=field,
                )
            )
        self.ensure_one()
        if res_ids_lang:
            templates_res_ids = {}
            default_lang = self.env.context.get("lang")
            for res_id in res_ids:
                lang = res_ids_lang.get(res_id, default_lang)
                if lang not in templates_res_ids:
                    templates_res_ids[lang] = (self._with_render_lang(lang), [])
                templates_res_ids[lang][1].append(res_id)
        elif compute_lang:
            templates_res_ids = self._classify_per_lang(res_ids)
        elif set_lang:
            templates_res_ids = {set_lang: (self.with_context(lang=set_lang), res_ids)}
        else:
            templates_res_ids = {self.env.context.get("lang"): (self, res_ids)}

        template_field = self._fields[field]
        engine = getattr(template_field, "render_engine", None) or engine
        render_options = {
            **(getattr(template_field, "render_options", None) or {}),
            **(options or {}),
        }

        return {
            res_id: rendered
            for (template, tpl_res_ids) in templates_res_ids.values()
            for res_id, rendered in template._render_template(
                template[field],
                template.render_model,
                tpl_res_ids,
                engine=engine,
                add_context=add_context,
                options=render_options,
            ).items()
        }


def _format_template_value(value: Any) -> str:
    if isinstance(value, models.BaseModel):
        return value.display_name or ""
    return str(value)
