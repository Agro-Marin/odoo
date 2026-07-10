import base64
import binascii
import logging
import math
from datetime import date, datetime, time
from io import BytesIO
from typing import Any

import babel.dates
from lxml import etree, html
from markupsafe import Markup, escape
from PIL import Image

from odoo import api, fields, models, tools
from odoo.libs.filesystem.mimetypes import guess_mimetype
from odoo.libs.numbers import float_utils
from odoo.libs.text.html import nl2br
from odoo.tools import (
    float_is_zero,
    format_date,
    format_duration,
    posix_to_ldml,
)
from odoo.tools.mail import safe_attrs
from odoo.tools.misc import babel_locale_parse, get_lang
from odoo.tools.translate import LazyTranslate, _

_lt = LazyTranslate(__name__)
_logger = logging.getLogger(__name__)

# Glue the minus sign to the digits it negates with a zero-width no-break space
# so bidi/RTL reflow cannot detach it from its number. Shared by every numeric
# widget (integer/float/monetary) via ``IrQwebField._format_number``.
NEGATIVE_SIGN_JOINER = "-\N{ZERO WIDTH NO-BREAK SPACE}"

# --------------------------------------------------------------------
# QWeb Fields converters
# --------------------------------------------------------------------


class IrQwebField(models.AbstractModel):
    """Convert a ``t-field``/``t-out`` value into output HTML.

    :meth:`~.record_to_html` formats a field off a record (``t-field`` path)
    and :meth:`~.value_to_html` formats a bare value (``t-out`` widget path);
    :meth:`~.attributes` builds the ``data-oe-*`` metadata for inline editing.
    """

    _name = "ir.qweb.field"
    _description = "Qweb Field"

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        """Return the available options as ``{name: settings}``.

        Each settings dict has guaranteed ``type`` (one of ``string``,
        ``integer``, ``float``, ``model``, ``array``, ``selection``) and
        ``string`` keys, plus optional ``description``, ``required`` (``False``
        when absent, else ``True`` or a string), ``params`` and ``default_value``
        (json-friendly).
        """
        return {}

    @api.model
    def attributes(
        self,
        record: models.BaseModel,
        field_name: str,
        options: dict[str, Any],
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the ``data-oe-*`` metadata attributes for the field's root node.

        Covers model, id, field, type, expression and (if readonly) readonly.
        ``type`` is the logical widget type, which may not match the field's
        ``type`` nor any Field subclass name.
        """
        data = {}
        field = record._fields[field_name]

        # ``inherit_branding``/``translate`` are injected by the ``t-field``
        # dispatcher, but keep this tolerant of direct callers that omit them.
        if not options.get("inherit_branding") and not options.get("translate"):
            return data

        data["data-oe-model"] = record._name
        data["data-oe-id"] = record.id
        data["data-oe-field"] = field.name
        data["data-oe-type"] = options.get("type")
        data["data-oe-expression"] = options.get("expression")
        if field.readonly:
            data["data-oe-readonly"] = 1
        return data

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup:
        """Convert a single value to its HTML output."""
        if value is None or value is False:
            return ""

        return escape(value.decode() if isinstance(value, bytes) else value)

    @api.model
    def _get_record_context_keys(self) -> list[str]:
        """Context keys propagated from the rendering environment onto the
        record when reading the field value in :meth:`record_to_html`."""
        return self.env["ir.qweb"]._get_template_cache_keys() + ["tz", "bin_size"]

    @api.model
    def record_to_html(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> str | Markup | bool:
        """Convert the given field of ``record`` to HTML."""
        if not record:
            return False
        # Read the field through the QWeb presentation context (lang, tz,
        # bin_size, …) so the value renders as it should. Only that curated
        # subset is propagated: the full rendering context carries qweb-internal
        # per-render state that a blanket with_context(**self.env.context) would
        # drag into every downstream compute, once per t-field cell.
        env_context = self.env.context
        record_context = record.env.context
        context_delta = {
            key: env_context[key]
            for key in self._get_record_context_keys()
            if key in env_context and record_context.get(key) != env_context[key]
        }
        if context_delta:
            record = record.with_context(**context_delta)
        value = record[field_name]
        return (
            False
            if value is False or value is None
            else self.value_to_html(value, options=options)
        )

    @api.model
    def user_lang(self) -> models.BaseModel:
        """Return the ``res.lang`` record for the language in the user's context."""
        return self.env["res.lang"].browse(get_lang(self.env).id)

    @api.model
    def _format_number(
        self,
        number_format: str,
        value: Any,
        grouping: bool = True,
        lang: models.BaseModel | None = None,
    ) -> str:
        """Locale-format ``value`` with ``number_format`` (a single ``%``
        specifier) and keep the negative sign glued to its digits.

        Shared by the integer/float/monetary widgets, which all need the same
        locale grouping + bidi-safe minus handling.

        :param lang: optional pre-resolved ``res.lang`` record; callers that
            already hold one (e.g. monetary) pass it to avoid a second
            ``user_lang()`` resolution per value.
        """
        return (
            (lang or self.user_lang())
            .format(number_format, value, grouping=grouping)
            .replace("-", NEGATIVE_SIGN_JOINER)
        )


class IrQwebFieldInteger(models.AbstractModel):
    _name = "ir.qweb.field.integer"
    _description = "Qweb Field Integer"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        options.update(
            format_decimalized_number={
                "type": "boolean",
                "string": _("Decimalized number"),
            },
            precision_digits={
                "type": "integer",
                "string": _("Precision Digits"),
            },
        )
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        if options.get("format_decimalized_number"):
            return tools.misc.format_decimalized_number(
                value, options.get("precision_digits", 1)
            )
        return self._format_number("%d", value)


class IrQwebFieldFloat(models.AbstractModel):
    _name = "ir.qweb.field.float"
    _description = "Qweb Field Float"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        options.update(
            precision={"type": "integer", "string": _("Rounding precision")},
        )
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        min_precision = options.get("min_precision")
        if "decimal_precision" in options:
            precision = self.env["decimal.precision"].precision_get(
                options["decimal_precision"]
            )
        elif options.get("precision") is None:
            int_digits = int(math.log10(abs(value))) + 1 if value != 0 else 1
            # Cap significant digits near a double's ~15-16 digit limit. The
            # value is rendered through f"%.{precision}f" below (exactly
            # `precision` decimals), so float_round noise beyond it never shows.
            max_dec_digits = max(15 - int_digits, 0)
            # We display maximum 6 decimal digits or the number of significant decimal digits if it's lower
            precision = min(6, max_dec_digits)
            min_precision = min_precision or 1
        else:
            precision = options["precision"]

        fmt = f"%.{precision}f"
        if min_precision and min_precision < precision:
            _, dec_part = float_utils.float_split_str(value, precision)
            digits_count = len(dec_part.rstrip("0"))
            if digits_count < min_precision:
                fmt = f"%.{min_precision}f"
            elif digits_count < precision:
                fmt = f"%.{digits_count}f"

        value = float_utils.float_round(value, precision_digits=precision)
        return self._format_number(fmt, value)

    @api.model
    def record_to_html(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> str | Markup | bool:
        field = record._fields[field_name]
        if "precision" not in options and "decimal_precision" not in options:
            _, precision = field.get_digits(record.env) or (None, None)
            # Only inject ``precision`` when the field declares digits: a
            # ``None`` would otherwise reach ``f"%.{precision}f"`` as the literal
            # ``"%.Nonef"``. Leaving it out lets ``value_to_html`` derive it.
            if precision is not None:
                options = dict(options, precision=precision)
        if "min_precision" not in options and hasattr(field, "get_min_display_digits"):
            min_precision = field.get_min_display_digits(record.env)
            options = dict(options, min_precision=min_precision)
        return super().record_to_html(record, field_name, options)


class IrQwebFieldDate(models.AbstractModel):
    _name = "ir.qweb.field.date"
    _description = "Qweb Field Date"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        options.update(format={"type": "string", "string": _("Date format")})
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        return format_date(self.env, value, date_format=options.get("format"))


class IrQwebFieldDatetime(models.AbstractModel):
    _name = "ir.qweb.field.datetime"
    _description = "Qweb Field Datetime"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        options.update(
            format={"type": "string", "string": _("Pattern to format")},
            tz_name={"type": "char", "string": _("Optional timezone name")},
            time_only={"type": "boolean", "string": _("Display only the time")},
            hide_seconds={"type": "boolean", "string": _("Hide seconds")},
            date_only={"type": "boolean", "string": _("Display only the date")},
        )
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        if not value:
            return ""

        lang = self.user_lang()
        locale = babel_locale_parse(lang.code)
        if isinstance(value, str):
            value = fields.Datetime.from_string(value)

        # ``context_timestamp`` reads the tz off the record's context; use a
        # local rather than rebinding ``self`` when an explicit tz is requested.
        record = self
        if options.get("tz_name"):
            record = self.with_context(tz=options["tz_name"])
            tzinfo = babel.dates.get_timezone(options["tz_name"])
        else:
            tzinfo = None

        value = fields.Datetime.context_timestamp(record, value)

        if "format" in options:
            pattern = options["format"]
        else:
            if options.get("time_only"):
                strftime_pattern = lang.time_format
            elif options.get("date_only"):
                strftime_pattern = lang.date_format
            else:
                strftime_pattern = f"{lang.date_format} {lang.time_format}"

            pattern = posix_to_ldml(strftime_pattern, locale=locale)

        if options.get("hide_seconds"):
            pattern = pattern.replace(":ss", "").replace(":s", "")

        if options.get("time_only"):
            return babel.dates.format_time(
                value, format=pattern, tzinfo=tzinfo, locale=locale
            )
        elif options.get("date_only"):
            return babel.dates.format_date(value, format=pattern, locale=locale)
        else:
            return babel.dates.format_datetime(
                value, format=pattern, tzinfo=tzinfo, locale=locale
            )


class IrQwebFieldText(models.AbstractModel):
    _name = "ir.qweb.field.text"
    _description = "Qweb Field Text"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup:
        """Escape the value and convert newlines to HTML line breaks."""
        return nl2br(value) if value else ""


class IrQwebFieldSelection(models.AbstractModel):
    _name = "ir.qweb.field.selection"
    _description = "Qweb Field Selection"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        options.update(
            selection={
                "type": "json",
                "string": _("Json"),
                "description": _("By default the widget uses the field information"),
                "required": True,
            }
        )
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup:
        if value is None or value is False:
            return ""
        return escape(options["selection"].get(value, value) or "")

    @api.model
    def record_to_html(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> str | Markup | bool:
        if "selection" not in options:
            # Only the selection pairs are needed; ``get_description`` built
            # (and translated) the field's entire description per rendered cell.
            options = dict(
                options,
                selection=dict(
                    record._fields[field_name]._description_selection(self.env)
                ),
            )
        return super().record_to_html(record, field_name, options)


class IrQwebFieldMany2one(models.AbstractModel):
    _name = "ir.qweb.field.many2one"
    _description = "Qweb Field Many to One"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup | bool:
        if not value:
            return False
        value = value.sudo().display_name
        if not value:
            return False
        return nl2br(value)


class IrQwebFieldMany2many(models.AbstractModel):
    _name = "ir.qweb.field.many2many"
    _description = "Qweb field many2many"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup | bool:
        if not value:
            return False
        text = ", ".join(value.sudo().mapped("display_name"))
        return nl2br(text)


class IrQwebFieldOne2many(models.AbstractModel):
    # Identical rendering to many2many (comma-joined display names); inherit it
    # rather than duplicate the body.
    _name = "ir.qweb.field.one2many"
    _description = "Qweb field one2many"
    _inherit = ["ir.qweb.field.many2many"]


class IrQwebFieldHtml(models.AbstractModel):
    """``html`` converter, emits the stored markup as-is (no sanitization here)."""

    # This converter does NOT sanitize: it re-serializes the stored HTML and only
    # runs attribute post-processing (e.g. asset rewriting). Safety relies on the
    # ``Html`` field sanitizing on write (sanitize=True by default,
    # sanitize_overridable gated by base.group_sanitize_override). Do not point
    # it at sanitize=False content originating from untrusted sources.
    _name = "ir.qweb.field.html"
    _description = "Qweb Field HTML"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> Markup:
        if not value:
            # The widget path (t-out widget='html') reaches this converter with
            # the ORM falsy value (False/None) for an unset html field. Without
            # this guard the f-string below interpolates the literal text,
            # rendering "False"/"None"; the t-field path is guarded upstream.
            return Markup("")
        irQweb = self.env["ir.qweb"]
        # Wrap in a <body> so the fragment parses as HTML.
        body = etree.fromstring(
            f"<body>{value}</body>", etree.HTMLParser(encoding="utf-8")
        )[0]
        for element in body.iter():
            if element.attrib:
                attrib = dict(element.attrib)
                # Stored (user) HTML is dynamic content: keep the default
                # ``is_static=False`` so the malicious-scheme scrub applies.
                attrib = irQweb._post_processing_att(element.tag, attrib)
                element.attrib.clear()
                element.attrib.update(attrib)
        serialized = etree.tostring(body, encoding="unicode", method="html")
        # strip the wrapping <body>…</body> added above to isolate the content
        return Markup(serialized.removeprefix("<body>").removesuffix("</body>"))


class IrQwebFieldImage(models.AbstractModel):
    """``image`` widget rendering, inserts a data:uri-using image tag in the
    document. May be overridden by e.g. the website module to generate links
    instead.

    .. todo:: what happens if different output need different converters? e.g.
              reports may need embedded images or FS links whereas website
              needs website-aware
    """

    _name = "ir.qweb.field.image"
    _description = "Qweb Field Image"
    _inherit = ["ir.qweb.field"]

    @api.model
    def _get_src_data_b64(self, value: Any, options: dict[str, Any]) -> str:
        try:
            img_b64 = base64.b64decode(value)
        except binascii.Error:
            msg = "Invalid image content"
            raise ValueError(msg) from None

        mimetype = guess_mimetype(img_b64, "") if img_b64 else None
        if mimetype == "image/webp":
            return self.env["ir.qweb"]._get_converted_image_data_uri(value)
        elif mimetype != "image/svg+xml":
            try:
                image = Image.open(BytesIO(img_b64))
                image.verify()
                mimetype = Image.MIME[image.format]
            except OSError as exc:
                msg = "Non-image binary fields can not be converted to HTML"
                raise ValueError(msg) from exc
            except SyntaxError as exc:
                msg = "Invalid image content"
                raise ValueError(msg) from exc

        return f"data:{mimetype};base64,{value.decode('ascii')}"

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> Markup:
        return Markup('<img src="%s">') % self._get_src_data_b64(value, options)


class IrQwebFieldImage_Url(models.AbstractModel):
    """``image_url`` widget rendering, inserts an image tag in the
    document.
    """

    _name = "ir.qweb.field.image_url"
    _description = "Qweb Field Image"
    _inherit = ["ir.qweb.field.image"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> Markup:
        return Markup('<img src="%s">') % value


class IrQwebFieldMonetary(models.AbstractModel):
    """``monetary`` converter. ``display_currency`` is required unless the field
    is a Monetary one (which must then declare a ``currency_field``).

    The currency drives formatting *and rounding* (via res.currency's ``round``);
    the linked res.currency is assumed to have a non-empty rounding value.
    """

    _name = "ir.qweb.field.monetary"
    _description = "Qweb Field Monetary"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        options.update(
            from_currency={
                "type": "model",
                "params": "res.currency",
                "string": _("Original currency"),
            },
            display_currency={
                "type": "model",
                "params": "res.currency",
                "string": _("Display currency"),
                "required": "value_to_html",
            },
            date={
                "type": "date",
                "string": _("Date"),
                "description": _(
                    "Date used for the original currency (only used for t-esc). by default use the current date."
                ),
            },
            company_id={
                "type": "model",
                "params": "res.company",
                "string": _("Company"),
                "description": _(
                    "Company used for the original currency (only used for t-esc). By default use the user company"
                ),
            },
        )
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> Markup:
        display_currency = options.get("display_currency")
        if not display_currency:
            msg = "Missing display_currency option for monetary field rendering."
            raise ValueError(msg)

        # ``bool`` is a subclass of ``int``; reject it explicitly so a stray
        # boolean isn't silently formatted as a currency amount.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(_("The value send to monetary field is not a number."))

        # lang.format needs an explicit sprintf precision (it sets none by
        # default, nor does currency.round), so derive one from the currency's
        # decimal_places.
        decimal_places = options.get("decimal_places", display_currency.decimal_places)
        fmt = f"%.{decimal_places}f"

        if options.get("from_currency"):
            date = options.get("date") or fields.Date.today()
            company_id = options.get("company_id")
            if company_id:
                company = self.env["res.company"].browse(company_id)
            else:
                company = self.env.company
            value = options["from_currency"]._convert(
                value, display_currency, company, date
            )

        if float_is_zero(value, precision_digits=display_currency.decimal_places):
            value = 0.0

        lang = self.user_lang()
        formatted_amount = self._format_number(
            fmt, display_currency.round(value), lang=lang
        ).replace(" ", "\N{NO-BREAK SPACE}")

        symbol = display_currency.symbol or ""
        pre = post = ""
        if display_currency.position == "before":
            pre = f"{symbol}\N{NO-BREAK SPACE}"
        else:
            post = f"\N{NO-BREAK SPACE}{symbol}"

        if options.get("label_price") and lang.decimal_point in formatted_amount:
            sep = lang.decimal_point
            integer_part, decimal_part = formatted_amount.split(sep)
            integer_part += sep
            return Markup(
                '{pre}<span class="oe_currency_value">{0}</span><span class="oe_currency_value" style="font-size:0.5em">{1}</span>{post}'
            ).format(integer_part, decimal_part, pre=pre, post=post)

        return Markup('{pre}<span class="oe_currency_value">{0}</span>{post}').format(
            formatted_amount, pre=pre, post=post
        )

    @api.model
    def record_to_html(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> str | Markup | bool:
        options = dict(options)
        field = record._fields[field_name]

        if not options.get("display_currency") and field.type == "monetary":
            currency_field_name = field.get_currency_field(record)
            if currency_field_name:
                options["display_currency"] = record[currency_field_name]
        if not options.get("display_currency"):
            # Fall back to the model's first res.currency many2one.
            currency_fields = [
                k
                for k, v in record._fields.items()
                if v.type == "many2one" and v.comodel_name == "res.currency"
            ]
            if currency_fields:
                options["display_currency"] = record[currency_fields[0]]
        if "date" not in options:
            options["date"] = record.env.context.get("date")
        if "company_id" not in options:
            options["company_id"] = record.env.context.get("company_id")

        return super().record_to_html(record, field_name, options)


TIMEDELTA_UNITS = (
    ("year", _lt("year"), 3600 * 24 * 365),
    ("month", _lt("month"), 3600 * 24 * 30),
    ("week", _lt("week"), 3600 * 24 * 7),
    ("day", _lt("day"), 3600 * 24),
    ("hour", _lt("hour"), 3600),
    ("minute", _lt("minute"), 60),
    ("second", _lt("second"), 1),
)

# unit name -> seconds, derived once (the duration widget looks units up by
# name on every render).
TIMEDELTA_SECONDS_BY_UNIT = {unit: seconds for unit, _label, seconds in TIMEDELTA_UNITS}


class IrQwebFieldFloat_Time(models.AbstractModel):
    """``float_time`` converter, to display integral or fractional values as
    human-readable time spans (e.g. 1.5 as "01:30").

    Can be used on any numerical field.
    """

    _name = "ir.qweb.field.float_time"
    _description = "Qweb Field Float Time"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        return format_duration(value)


class IrQwebFieldTime(models.AbstractModel):
    """``time`` converter, to display integer or fractional value as
    human-readable time (e.g. 1.5 as "1:30 AM"). The unit of this value
    is in hours.

    Can be used on any numerical field between: 0 <= value < 24
    """

    _name = "ir.qweb.field.time"
    _description = "QWeb Field Time"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        if value < 0:
            raise ValueError(_("The value (%s) passed should be positive", value))
        # ``value`` is guaranteed non-negative by the check above, no abs() needed.
        hours, minutes = divmod(int(value * 60), 60)
        if hours > 23:
            raise ValueError(_("The hour must be between 0 and 23"))
        t = time(hour=hours, minute=minutes)

        locale = babel_locale_parse(self.user_lang().code)
        pattern = options.get("format", "short")

        return babel.dates.format_time(t, format=pattern, tzinfo=None, locale=locale)


class IrQwebFieldDuration(models.AbstractModel):
    """``duration`` converter: display a numerical value as a human-readable
    time span (e.g. 1.5 as "1 hour 30 minutes"). Sub-second values are ignored.

    Options: ``unit`` (second/minute/hour/day/week/month/year, default second)
    interprets the value; ``round`` (default second); ``digital`` shows 01:00
    instead of "1 hour".
    """

    _name = "ir.qweb.field.duration"
    _description = "Qweb Field Duration"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        unit = [(value, str(label)) for value, label, ratio in TIMEDELTA_UNITS]
        options.update(
            digital={"type": "boolean", "string": _("Digital formatting")},
            unit={
                "type": "selection",
                "params": unit,
                "string": _("Date unit"),
                "description": _("Date unit used for comparison and formatting"),
                "default_value": "second",
                "required": True,
            },
            round={
                "type": "selection",
                "params": unit,
                "string": _("Rounding unit"),
                "description": _(
                    "Date unit used for the rounding. The value must be smaller than 'hour' if you use the digital formatting."
                ),
                "default_value": "second",
            },
            format={
                "type": "selection",
                "params": [
                    ("long", _("Long")),
                    ("short", _("Short")),
                    ("narrow", _("Narrow")),
                ],
                "string": _("Format"),
                "description": _(
                    "Formatting: long, short, narrow (not used for digital)"
                ),
                "default_value": "long",
            },
            add_direction={
                "type": "boolean",
                "string": _("Add direction"),
                "description": _("Add directional information (not used for digital)"),
            },
        )
        return options

    @api.model
    def _format_timedelta_section(
        self,
        seconds: float,
        granularity: int,
        add_direction: Any,
        fmt: str,
        locale: Any,
    ) -> str:
        """Wrap :func:`babel.dates.format_timedelta` with an en_US fallback.

        Some babel builds (e.g. the 2.8 shipped on ubuntu22) miss locale data
        and raise ``KeyError``; retry once against en_US.
        https://github.com/python-babel/babel/pull/827
        """
        kwargs = {
            "granularity": granularity,
            "add_direction": add_direction,
            "format": fmt,
            "threshold": 1,
        }
        try:
            return babel.dates.format_timedelta(seconds, locale=locale, **kwargs)
        except KeyError:
            return babel.dates.format_timedelta(
                seconds, locale=babel_locale_parse("en_US"), **kwargs
            )

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        units = TIMEDELTA_SECONDS_BY_UNIT

        locale = babel_locale_parse(self.user_lang().code)
        factor = units[options.get("unit", "second")]
        round_to = units[options.get("round", "second")]

        if options.get("digital") and round_to > 3600:
            round_to = 3600

        r = round((value * factor) / round_to) * round_to

        sections = []
        sign = ""
        if value < 0:
            r = -r
            sign = "-"

        if options.get("digital"):
            for _unit, _label, secs_per_unit in TIMEDELTA_UNITS:
                if secs_per_unit > 3600:
                    continue
                v, r = divmod(r, secs_per_unit)
                if not v and (secs_per_unit > factor or secs_per_unit < round_to):
                    continue
                sections.append("%02.0f" % round(v))
            return sign + ":".join(sections)

        for _unit, _label, secs_per_unit in TIMEDELTA_UNITS:
            v, r = divmod(r, secs_per_unit)
            if not v:
                continue
            section = self._format_timedelta_section(
                v * secs_per_unit,
                round_to,
                options.get("add_direction"),
                options.get("format", "long"),
                locale,
            )
            if section:
                sections.append(section)

        if sign:
            sections.insert(0, sign)
        return " ".join(sections)


class IrQwebFieldRelative(models.AbstractModel):
    _name = "ir.qweb.field.relative"
    _description = "Qweb Field Relative"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        options.update(
            now={
                "type": "datetime",
                "string": _("Reference date"),
                "description": _(
                    "Date to compare with the field value, by default use the current date."
                ),
            }
        )
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        locale = babel_locale_parse(self.user_lang().code)

        if isinstance(value, str):
            value = fields.Datetime.from_string(value)
        elif isinstance(value, date) and not isinstance(value, datetime):
            # A ``date`` value (date field) cannot be subtracted from the
            # datetime reference below; compare from its midnight.
            value = datetime.combine(value, time.min)

        # ``record_to_html`` injects ``now`` for the t-field path; on the bare
        # value (t-out widget) path it may be absent, so default to now. Both
        # value and reference are naive UTC datetimes.
        reference = fields.Datetime.from_string(
            options.get("now") or fields.Datetime.now()
        )

        return babel.dates.format_timedelta(
            value - reference, add_direction=True, locale=locale
        )

    @api.model
    def record_to_html(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> str | Markup | bool:
        if "now" not in options:
            field = record._fields[field_name]
            # ``fields.Date`` has no ``now()``: the reference is always a
            # datetime, whatever the field type.
            now = field.now() if field.type == "datetime" else fields.Datetime.now()
            options = dict(options, now=now)
        return super().record_to_html(record, field_name, options)


class IrQwebFieldBarcode(models.AbstractModel):
    """``barcode`` widget rendering, inserts a data:uri-using image tag in the
    document. May be overridden by e.g. the website module to generate links
    instead.
    """

    _name = "ir.qweb.field.barcode"
    _description = "Qweb Field Barcode"
    _inherit = ["ir.qweb.field"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        options.update(
            symbology={
                "type": "string",
                "string": _("Barcode symbology"),
                "description": _("Barcode type, eg: UPCA, EAN13, Code128"),
                "default_value": "Code128",
            },
            width={
                "type": "integer",
                "string": _("Width"),
                "default_value": 600,
            },
            height={
                "type": "integer",
                "string": _("Height"),
                "default_value": 100,
            },
            humanreadable={
                "type": "integer",
                "string": _("Human Readable"),
                "default_value": 0,
            },
            quiet={"type": "integer", "string": "Quiet", "default_value": 1},
            mask={"type": "string", "string": "Mask", "default_value": ""},
        )
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup:
        if not value:
            return ""
        if not value.isascii():
            return nl2br(value)
        barcode_symbology = options.get("symbology", "Code128")
        barcode = self.env["ir.actions.report"].barcode(
            barcode_symbology,
            value,
            **{
                k: v
                for k, v in options.items()
                if k in ["width", "height", "humanreadable", "quiet", "mask"]
            },
        )

        img_element = html.Element("img")
        for k, v in options.items():
            if k.startswith("img_") and k.removeprefix("img_") in safe_attrs:
                img_element.set(k.removeprefix("img_"), v)
        if not img_element.get("alt"):
            img_element.set("alt", _("Barcode %s", value))
        img_element.set(
            "src", f"data:image/png;base64,{base64.b64encode(barcode).decode()}"
        )
        return Markup(html.tostring(img_element, encoding="unicode"))


class IrQwebFieldContact(models.AbstractModel):
    _name = "ir.qweb.field.contact"
    _description = "Qweb Field Contact"
    _inherit = ["ir.qweb.field.many2one"]

    @api.model
    def get_available_options(self) -> dict[str, dict[str, Any]]:
        options = super().get_available_options()
        contact_fields = [
            {"field_name": "name", "label": _("Name"), "default": True},
            {"field_name": "address", "label": _("Address"), "default": True},
            {"field_name": "phone", "label": _("Phone"), "default": True},
            {"field_name": "email", "label": _("Email"), "default": True},
            {"field_name": "vat", "label": _("VAT")},
        ]
        separator_params = {
            "type": "selection",
            "selection": [
                [" ", _("Space")],
                [",", _("Comma")],
                ["-", _("Dash")],
                ["|", _("Vertical bar")],
                ["/", _("Slash")],
            ],
            "placeholder": _("Linebreak"),
        }
        options.update(
            fields={
                "type": "array",
                "params": {"type": "selection", "params": contact_fields},
                "string": _("Displayed fields"),
                "description": _("List of contact fields to display in the widget"),
                "default_value": [
                    param.get("field_name")
                    for param in contact_fields
                    if param.get("default")
                ],
            },
            separator={
                "type": "selection",
                "params": separator_params,
                "string": _("Address separator"),
                "description": _(
                    "Separator use to split the address from the display_name."
                ),
                "default_value": False,
            },
            no_marker={
                "type": "boolean",
                "string": _("Hide badges"),
                "description": _("Don't display the font awesome marker"),
            },
            no_tag_br={
                "type": "boolean",
                "string": _("Use comma"),
                "description": _(
                    "Use comma instead of the <br> tag to display the address"
                ),
            },
            phone_icons={
                "type": "boolean",
                "string": _("Display phone icons"),
                "description": _("Display the phone icons even if no_marker is True"),
            },
            country_image={
                "type": "boolean",
                "string": _("Display country image"),
                "description": _(
                    "Display the country image if the field is present on the record"
                ),
            },
        )
        return options

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup:
        if not value:
            if options.get("null_text"):
                val = {
                    "options": options,
                }
                template_options = options.get("template_options", {})
                return self.env["ir.qweb"]._render(
                    "base.no_contact", val, **template_options
                )
            return ""

        opf = options.get("fields") or ["name", "address", "phone", "email"]
        sep = options.get("separator")
        if sep:
            opsep = escape(sep)
        elif options.get("no_tag_br"):
            # escaped joiners will auto-escape joined params
            opsep = escape(", ")
        else:
            opsep = Markup("<br/>")

        value = value.sudo().with_context(show_address=True)
        display_name = value.display_name or ""
        name_line, *address_lines = display_name.split("\n")
        # Avoid e.g. display_name = 'Foo\n  \n' (name, no address) yielding a
        # markup('<br/>') address when there is no address.
        if any(elem.strip() for elem in address_lines):
            address = opsep.join(address_lines).strip()
        else:
            address = ""
        val = {
            "name": name_line,
            "address": address,
            "phone": value.phone,
            "city": value.city,
            "country_id": value.country_id.display_name,
            "website": value.website,
            "email": value.email,
            "vat": value.vat,
            "vat_label": value.country_id.vat_label or _("VAT"),
            "fields": opf,
            "object": value,
            "options": options,
        }
        return self.env["ir.qweb"]._render("base.contact", val, minimal_qcontext=True)


class IrQwebFieldQweb(models.AbstractModel):
    _name = "ir.qweb.field.qweb"
    _description = "Qweb Field qweb"
    _inherit = ["ir.qweb.field.many2one"]

    @api.model
    def record_to_html(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> str | Markup:
        view = record[field_name]
        if not view:
            return ""

        if view._name != "ir.ui.view":
            _logger.warning(
                "%s.%s must be a 'ir.ui.view', got %r.",
                record,
                field_name,
                view._name,
            )
            return ""

        return self.env["ir.qweb"]._render(view.id, options.get("values", {}))
