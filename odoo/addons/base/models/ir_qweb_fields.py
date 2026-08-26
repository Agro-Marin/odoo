import base64
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
from odoo.libs.filesystem import guess_mimetype
from odoo.libs.numbers import float_utils
from odoo.libs.text import nl2br
from odoo.tools import (
    NEGATIVE_SIGN_JOINER,
    format_amount_parts,
    format_date,
    format_duration,
    posix_to_ldml,
)
from odoo.tools.mail import safe_attrs
from odoo.tools.misc import babel_locale_parse, get_lang
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

TIMEDELTA_UNITS = (
    ("year", 3600 * 24 * 365),
    ("month", 3600 * 24 * 30),
    ("week", 3600 * 24 * 7),
    ("day", 3600 * 24),
    ("hour", 3600),
    ("minute", 60),
    ("second", 1),
)

TIMEDELTA_SECONDS_BY_UNIT = dict(TIMEDELTA_UNITS)

# The `fields` the contact widget shows when the option is not given.
# `base.contact` also understands "city" and "country_id"; two shipped
# templates pass them, so the list a caller may send is wider than this.
CONTACT_DEFAULT_FIELDS = ("name", "address", "phone", "email")

BARCODE_RENDER_OPTIONS = frozenset(
    ("width", "height", "humanreadable", "quiet", "mask")
)


class IrQwebField(models.AbstractModel):
    _name = "ir.qweb.field"
    _description = "Qweb Field"

    @api.model
    def attributes(
        self,
        record: models.BaseModel,
        field_name: str,
        options: dict[str, Any],
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = {}
        if not options.get("inherit_branding") and not options.get("translate"):
            return data

        field = record._fields[field_name]
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
        if value is None or value is False:
            return ""

        if isinstance(value, bytes):
            # A binary field's bytes are base64 ASCII, but `t-out` reaches here
            # with whatever the expression evaluated to, and a bare `.decode()`
            # took the whole page down with UnicodeDecodeError on the first
            # non-UTF-8 byte. Replace rather than raise: this is the fallback
            # converter, and a mojibake cell beats a 500.
            value = value.decode(errors="replace")
        return escape(value)

    @api.model
    def _get_record_context_keys(self) -> list[str]:
        return self.env["ir.qweb"]._get_template_cache_keys() + ["tz", "bin_size"]

    @api.model
    def _record_options(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        return options

    @api.model
    def record_to_html(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> str | Markup | bool:
        if not record:
            return False
        options = self._record_options(record, field_name, options)
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
        return self.env["res.lang"].browse(get_lang(self.env).id)

    @api.model
    def _format_number(
        self,
        number_format: str,
        value: Any,
        grouping: bool = True,
        lang: models.BaseModel | None = None,
    ) -> str:
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
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        if not math.isfinite(value):
            # inf/nan reach `int(math.log10(...))` and `float_round` and come
            # back as OverflowError/ValueError from inside the formatter. No
            # column produces one, but a computed t-out expression can.
            msg = f"The value passed to the float field is not finite: {value!r}"
            raise ValueError(msg)
        min_precision = options.get("min_precision")
        if "decimal_precision" in options:
            precision = self.env["decimal.precision"].get_precision(
                options["decimal_precision"]
            )
        elif options.get("precision") is None:
            int_digits = int(math.log10(abs(value))) + 1 if value != 0 else 1
            max_dec_digits = max(15 - int_digits, 0)
            precision = min(6, max_dec_digits)
            min_precision = min_precision or 1
        else:
            precision = options["precision"]

        fmt = f"%.{precision}f"
        if min_precision and min_precision < precision:
            _int_part, dec_part = float_utils.float_split_str(value, precision)
            digits_count = len(dec_part.rstrip("0"))
            if digits_count < min_precision:
                fmt = f"%.{min_precision}f"
            elif digits_count < precision:
                fmt = f"%.{digits_count}f"

        value = float_utils.float_round(value, precision_digits=precision)
        return self._format_number(fmt, value)

    @api.model
    def _record_options(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        field = record._fields[field_name]
        defaults = {}
        if "precision" not in options and "decimal_precision" not in options:
            digits = field.get_digits(record.env)
            if digits:
                defaults["precision"] = digits[1]
        get_min_display_digits = getattr(field, "get_min_display_digits", None)
        if "min_precision" not in options and get_min_display_digits is not None:
            defaults["min_precision"] = get_min_display_digits(record.env)
        return dict(options, **defaults) if defaults else options


class IrQwebFieldDate(models.AbstractModel):
    _name = "ir.qweb.field.date"
    _description = "Qweb Field Date"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        return format_date(self.env, value, date_format=options.get("format"))


class IrQwebFieldDatetime(models.AbstractModel):
    _name = "ir.qweb.field.datetime"
    _description = "Qweb Field Datetime"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        if not value:
            return ""

        lang = self.user_lang()
        locale = babel_locale_parse(lang.code)
        if isinstance(value, str):
            value = fields.Datetime.from_string(value)
        elif isinstance(value, date) and not isinstance(value, datetime):
            # widget="datetime" over a date field: midnight, rather than the
            # bare AssertionError ``context_timestamp`` raises on a ``date``.
            value = datetime.combine(value, time.min)

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
        return nl2br(value) if value else ""


class IrQwebFieldSelection(models.AbstractModel):
    _name = "ir.qweb.field.selection"
    _description = "Qweb Field Selection"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup:
        if value is None or value is False:
            return ""
        selection = options.get("selection")
        if selection is None:
            msg = (
                "Missing 'selection' option for selection field rendering; "
                "t-out with widget='selection' must supply the label map that "
                "t-field reads off the field."
            )
            raise ValueError(msg)
        return escape(selection.get(value, value) or "")

    @api.model
    def _record_options(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        if "selection" in options:
            return options
        field = record._fields[field_name]
        return dict(options, selection=dict(field._description_selection(self.env)))


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
    _name = "ir.qweb.field.one2many"
    _description = "Qweb field one2many"
    _inherit = ["ir.qweb.field.many2many"]


class IrQwebFieldHtml(models.AbstractModel):
    _name = "ir.qweb.field.html"
    _description = "Qweb Field HTML"
    _inherit = ["ir.qweb.field"]

    @api.model
    def _post_process_html_body(
        self, body: etree._Element, options: dict[str, Any]
    ) -> etree._Element:
        # Mutate the parsed <body> in place, inside the ONE parse this
        # converter performs. `website` used to re-parse and re-serialise the
        # finished string to inject its form signature -- two extra round-trips
        # for every html field carrying a <form>.
        return body

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> Markup:
        if not value:
            return Markup("")
        irQweb = self.env["ir.qweb"]
        body = etree.fromstring(
            f"<body>{value}</body>", etree.HTMLParser(encoding="utf-8")
        )[0]
        # Asked once per document, not per element: a bound method call per
        # element cost more than the elements it skipped.
        att_names = irQweb._get_post_processing_att_names()
        for element in body.iter():
            attrib = element.attrib
            # Two skips, both output-neutral and both measured. Rewriting the
            # attributes of every element that has any was the dominant cost of
            # this loop, and `_post_processing_att` leaves almost all of them
            # alone.
            if not attrib:
                continue
            if att_names is not None and att_names.isdisjoint(attrib):
                continue
            # `_post_processing_att` mutates the dict it is handed, but that
            # dict is a copy -- `attrib` itself still holds the original, so it
            # is the thing to compare against and no second copy is needed.
            processed = irQweb._post_processing_att(element.tag, dict(attrib))
            if len(processed) != len(attrib) or any(
                attrib.get(name) != value for name, value in processed.items()
            ):
                attrib.clear()
                attrib.update(processed)
        body = self._post_process_html_body(body, options)
        serialized = etree.tostring(body, encoding="unicode", method="html")
        return Markup(serialized.removeprefix("<body>").removesuffix("</body>"))


class IrQwebFieldImage(models.AbstractModel):
    _name = "ir.qweb.field.image"
    _description = "Qweb Field Image"
    _inherit = ["ir.qweb.field"]

    @api.model
    def _get_src_data_b64(self, value: Any, options: dict[str, Any]) -> str:
        # A binary field hands over ``bytes``; ``t-out`` with widget="image"
        # hands over whatever the expression evaluated to. Normalise once and
        # STRICTLY -- this used to reach ``value.decode('ascii')`` at the very
        # end and raise AttributeError there, past every guard, for a plain
        # ``str``. Decoding leniently instead would be worse than the old
        # crash: ``b64decode`` discards a stray non-base64 byte, so the payload
        # would validate while the data URI built from the RAW value still
        # carried it.
        if isinstance(value, (bytes, bytearray, memoryview)):
            source = bytes(value)
        elif isinstance(value, str):
            source = value
        else:
            msg = "Invalid image content"
            raise ValueError(msg)

        try:
            img_b64 = base64.b64decode(source)
            value_b64 = source if isinstance(source, str) else source.decode("ascii")
        except ValueError:
            # binascii.Error and the "only ASCII characters" ValueError that
            # b64decode raises for a str both land here; so does the
            # UnicodeDecodeError from a bytes payload that is not ASCII.
            msg = "Invalid image content"
            raise ValueError(msg) from None

        mimetype = guess_mimetype(img_b64, "") if img_b64 else None
        if mimetype == "image/webp":
            return self.env["ir.qweb"]._get_converted_image_data_uri(value)
        elif mimetype != "image/svg+xml":
            sniffed = mimetype
            try:
                image = Image.open(BytesIO(img_b64))
                image.verify()
                # ``Image.MIME`` is populated per plugin and stays sparse: a
                # format Pillow can open is not necessarily one it has a MIME
                # for, and the bare index raised KeyError past both handlers.
                # Synthesise from the format name as a last resort -- `or
                # sniffed` alone put a literal "None" in the data URI when the
                # sniff came back empty too.
                mimetype = (
                    Image.MIME.get(image.format)
                    or sniffed
                    or (f"image/{image.format.lower()}" if image.format else None)
                )
                if not mimetype:
                    msg = "Invalid image content"
                    raise ValueError(msg)
            except OSError as exc:
                msg = "Non-image binary fields can not be converted to HTML"
                raise ValueError(msg) from exc
            except SyntaxError as exc:
                msg = "Invalid image content"
                raise ValueError(msg) from exc

        return f"data:{mimetype};base64,{value_b64}"

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> Markup:
        return Markup('<img src="%s">') % self._get_src_data_b64(value, options)


class IrQwebFieldImage_Url(models.AbstractModel):
    _name = "ir.qweb.field.image_url"
    _description = "Qweb Field Image"
    _inherit = ["ir.qweb.field.image"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> Markup:
        return Markup('<img src="%s">') % value


class IrQwebFieldMonetary(models.AbstractModel):
    _name = "ir.qweb.field.monetary"
    _description = "Qweb Field Monetary"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> Markup:
        display_currency = options.get("display_currency")
        if not display_currency:
            msg = "Missing display_currency option for monetary field rendering."
            raise ValueError(msg)

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            msg = f"The value passed to the monetary field is not a number: {value!r}"
            raise TypeError(msg)

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

        lang = self.user_lang()
        pre, formatted_amount, post = format_amount_parts(
            self.env,
            value,
            display_currency,
            lang_code=lang.code,
            decimal_places=options.get("decimal_places"),
        )

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
    def _currency_field_names(
        self, record: models.BaseModel, field_name: str
    ) -> list[str]:
        # An ORDER, not a pick: the caller takes the first that actually HOLDS
        # a currency. A monetary field's declared currency field can be empty
        # on a given record, and the fallback scan exists for that case.
        field = record._fields[field_name]
        declared = (
            field.get_currency_field(record) if field.type == "monetary" else None
        )
        candidates = [
            name
            for name, candidate in record._fields.items()
            if candidate.type == "many2one" and candidate.comodel_name == "res.currency"
        ]
        # The scan used to take candidates[0] -- whichever `_fields` happened to
        # yield first, which on product.template is `currency_id` only by luck
        # and is not a guarantee the field dict makes.
        ranked = sorted(
            candidates,
            key=lambda name: (name not in ("currency_id", "company_currency_id"), name),
        )
        if declared:
            ranked = [declared, *(name for name in ranked if name != declared)]
        return ranked

    @api.model
    def _record_options(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        options = dict(options)
        if not options.get("display_currency"):
            for name in self._currency_field_names(record, field_name):
                currency = record[name]
                if currency:
                    options["display_currency"] = currency
                    break
        options.setdefault("date", record.env.context.get("date"))
        options.setdefault("company_id", record.env.context.get("company_id"))
        return options


class IrQwebFieldFloat_Time(models.AbstractModel):
    _name = "ir.qweb.field.float_time"
    _description = "Qweb Field Float Time"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        return format_duration(value)


class IrQwebFieldTime(models.AbstractModel):
    _name = "ir.qweb.field.time"
    _description = "QWeb Field Time"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        if value < 0:
            msg = f"The value passed to the time field should be positive: {value!r}"
            raise ValueError(msg)
        if value >= 24:
            msg = f"The hour must be between 0 and 23, got {value!r}"
            raise ValueError(msg)
        # Round rather than truncate -- truncating rendered 22 of the day's
        # 1440 whole minutes one minute early, because `minutes / 60.0 * 60`
        # lands just below the integer. Clamp instead of raising on the way
        # back up: 23:59:31 rounds to 1440 minutes, and a value that used to
        # render must not start raising out of a template.
        minutes_total = min(round(value * 60), 24 * 60 - 1)
        hours, minutes = divmod(minutes_total, 60)
        t = time(hour=hours, minute=minutes)

        locale = babel_locale_parse(self.user_lang().code)
        pattern = options.get("format", "short")

        return babel.dates.format_time(t, format=pattern, tzinfo=None, locale=locale)


class IrQwebFieldDuration(models.AbstractModel):
    _name = "ir.qweb.field.duration"
    _description = "Qweb Field Duration"
    _inherit = ["ir.qweb.field"]

    @api.model
    def _format_timedelta(
        self,
        seconds: float,
        add_direction: bool,
        fmt: str,
        locale: Any,
    ) -> str:
        kwargs = {"add_direction": add_direction, "format": fmt, "threshold": 1}
        try:
            return babel.dates.format_timedelta(seconds, locale=locale, **kwargs)
        except KeyError:
            # Only the relative ("add_direction") patterns can be missing, and
            # only for the narrow/short widths: 57 (locale, width, unit) triples
            # across 28 CLDR locales lack a "future"/"past" entry, and every one
            # of them has the long width. Widen before giving up on the
            # language -- falling straight back to en_US, as this used to,
            # renders "in 1 hour" inside an otherwise Hungarian page.
            kwargs["format"] = "long"
            try:
                return babel.dates.format_timedelta(seconds, locale=locale, **kwargs)
            except KeyError:
                return babel.dates.format_timedelta(
                    seconds, locale=babel_locale_parse("en_US"), **kwargs
                )

    @api.model
    def _timedelta_unit_seconds(self, option: str, name: str) -> int:
        try:
            return TIMEDELTA_SECONDS_BY_UNIT[name]
        except KeyError:
            known = ", ".join(TIMEDELTA_SECONDS_BY_UNIT)
            msg = (
                f"Unknown {option!r} unit {name!r} for the duration widget; "
                f"expected one of: {known}"
            )
            raise ValueError(msg) from None

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        locale = babel_locale_parse(self.user_lang().code)
        factor = self._timedelta_unit_seconds("unit", options.get("unit", "second"))
        round_to = self._timedelta_unit_seconds("round", options.get("round", "second"))

        if options.get("digital") and round_to > 3600:
            round_to = 3600

        seconds = round((value * factor) / round_to) * round_to
        sign = "-" if seconds < 0 else ""
        remainder = abs(seconds)

        if options.get("digital"):
            sections = []
            for _unit, secs_per_unit in TIMEDELTA_UNITS:
                if secs_per_unit > 3600:
                    continue
                count, remainder = divmod(remainder, secs_per_unit)
                if not count and (secs_per_unit > factor or secs_per_unit < round_to):
                    continue
                sections.append("%02d" % count)
            return sign + ":".join(sections)

        fmt = options.get("format", "long")

        if options.get("add_direction"):
            # A direction cannot be composed with a section list. CLDR inflects
            # the unit noun in the relative form -- fr "1 heure" -> "dans 1
            # heure", pl "1 godzina" -> "za 1 godzinę" -- so the directed phrase
            # is not the plain one plus an affix, and only babel can mint it.
            # Directing each section instead produced "in 1h in 30m", which the
            # website_event_track countdown badges shipped.
            return (
                ""
                if not seconds
                else self._format_timedelta(seconds, True, fmt, locale)
            )

        sections = []
        for _unit, secs_per_unit in TIMEDELTA_UNITS:
            count, remainder = divmod(remainder, secs_per_unit)
            if not count:
                continue
            section = self._format_timedelta(count * secs_per_unit, False, fmt, locale)
            if section:
                sections.append(section)

        if not sections:
            return ""
        return sign + " ".join(sections)


class IrQwebFieldRelative(models.AbstractModel):
    _name = "ir.qweb.field.relative"
    _description = "Qweb Field Relative"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str:
        locale = babel_locale_parse(self.user_lang().code)

        if isinstance(value, str):
            value = fields.Datetime.from_string(value)
        elif isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, time.min)

        reference = fields.Datetime.from_string(
            options.get("now") or fields.Datetime.now()
        )

        return babel.dates.format_timedelta(
            value - reference, add_direction=True, locale=locale
        )

    @api.model
    def _record_options(
        self, record: models.BaseModel, field_name: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        if "now" in options:
            return options
        field = record._fields[field_name]
        now = field.now() if field.type == "datetime" else fields.Datetime.now()
        return dict(options, now=now)


class IrQwebFieldBarcode(models.AbstractModel):
    _name = "ir.qweb.field.barcode"
    _description = "Qweb Field Barcode"
    _inherit = ["ir.qweb.field"]

    @api.model
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup:
        if not value:
            return ""
        # A barcode is a string of symbols, but the field behind it is often an
        # integer (an EAN, a serial). ``isascii``/``prepare_barcode`` both want
        # ``str``; coerce here rather than raising AttributeError on the field.
        value = value if isinstance(value, str) else str(value)
        if not value.isascii():
            return nl2br(value)
        barcode_symbology = options.get("symbology", "Code128")
        barcode = self.env["ir.actions.report"].prepare_barcode(
            barcode_symbology,
            value,
            **{k: v for k, v in options.items() if k in BARCODE_RENDER_OPTIONS},
        )

        img_element = html.Element("img")
        for k, v in options.items():
            attribute = k.removeprefix("img_")
            if k.startswith("img_") and attribute in safe_attrs:
                img_element.set(attribute, v if isinstance(v, str) else str(v))
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
    def value_to_html(self, value: Any, options: dict[str, Any]) -> str | Markup:
        template_options = options.get("template_options") or {}
        if not value:
            if options.get("null_text"):
                # `minimal_qcontext` on both branches: `base.no_contact` used
                # to render without it while `base.contact` rendered with it,
                # so the empty case silently carried the whole default qcontext
                # its own template never reads.
                return self.env["ir.qweb"]._render(
                    "base.no_contact",
                    {"options": options},
                    minimal_qcontext=True,
                    **template_options,
                )
            return ""

        opf = options.get("fields") or CONTACT_DEFAULT_FIELDS
        sep = options.get("separator")
        if sep:
            opsep = escape(sep)
        elif options.get("no_tag_br"):
            opsep = escape(", ")
        else:
            opsep = Markup("<br/>")

        value = value.sudo().with_context(show_address=True)
        display_name = value.display_name or ""
        name_line, *address_lines = display_name.split("\n")
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
        return self.env["ir.qweb"]._render(
            "base.contact", val, minimal_qcontext=True, **template_options
        )


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
