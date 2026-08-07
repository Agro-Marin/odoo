import locale
import logging
import threading
from typing import Any, Literal, Self

from odoo import _, api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import UserError, ValidationError
from odoo.libs.locale import format_number
from odoo.tools import OrderedSet
from odoo.tools.misc import ReadonlyDict

_logger = logging.getLogger(__name__)

_LOCALE_LOCK = threading.Lock()


class LangData(ReadonlyDict):
    """A ``dict``-like class which can access field value like a ``res.lang`` record.
    Note: This data class cannot store data for fields with the same name as
    ``dict`` methods, like ``dict.keys``.
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return bool(self.id)

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError from None


class LangDataDict(ReadonlyDict):
    """A ``dict`` of :class:`LangData` objects indexed by some key, which returns
    a special dummy :class:`LangData` for missing keys.
    """

    __slots__ = ()

    def __getitem__(self, key: Any) -> LangData:
        try:
            return self._data__[key]
        except KeyError:
            some_lang = next(iter(self.values()), None)
            if some_lang is None:
                msg = "LangData is empty: at least one active language must exist"
                raise RuntimeError(msg) from None
            return LangData(dict.fromkeys(some_lang, False))


class ResLang(models.Model):
    _name = "res.lang"
    _description = "Languages"
    _order = "active desc,name"
    _allow_sudo_commands = False

    _disallowed_datetime_patterns = list(tools.misc.DATETIME_FORMATS_MAP)
    _disallowed_datetime_patterns.remove("%y")

    def _get_date_format_selection(self) -> list[tuple[str, str]]:
        current_year = fields.Date.today().year
        return [
            ("%d/%m/%Y", f"31/01/{current_year}"),
            ("%m/%d/%Y", f"01/31/{current_year}"),
            ("%Y/%m/%d", f"{current_year}/01/31"),
            ("%d-%m-%Y", f"31-01-{current_year}"),
            ("%m-%d-%Y", f"01-31-{current_year}"),
            ("%Y-%m-%d", f"{current_year}-01-31"),
            ("%d.%m.%Y", f"31.01.{current_year}"),
            ("%m.%d.%Y", f"01.31.{current_year}"),
            ("%Y.%m.%d", f"{current_year}.01.31"),
        ]

    name = fields.Char(required=True)
    code = fields.Char(
        string="Locale Code",
        required=True,
        help="This field is used to set/get locales for user",
    )
    iso_code = fields.Char(
        string="ISO code",
        help="This ISO code is the name of po files to use for translations",
    )
    url_code = fields.Char(
        "URL Code", required=True, help="The Lang Code displayed in the URL"
    )
    active = fields.Boolean()
    direction = fields.Selection(
        [("ltr", "Left-to-Right"), ("rtl", "Right-to-Left")],
        required=True,
        default="ltr",
    )
    date_format = fields.Selection(
        selection=_get_date_format_selection,
        string="Date Format",
        required=True,
        default="%m/%d/%Y",
    )
    time_format = fields.Selection(
        [
            ("%H:%M:%S", "13:00:00"),
            ("%I:%M:%S %p", " 1:00:00 PM"),
        ],
        string="Time Format",
        required=True,
        default="%H:%M:%S",
    )
    week_start = fields.Selection(
        [
            ("1", "Monday"),
            ("2", "Tuesday"),
            ("3", "Wednesday"),
            ("4", "Thursday"),
            ("5", "Friday"),
            ("6", "Saturday"),
            ("7", "Sunday"),
        ],
        string="First Day of Week",
        required=True,
        default="7",
    )
    grouping = fields.Selection(
        [
            ("[3,0]", "International Grouping"),
            ("[3,2,0]", "Indian Grouping"),
        ],
        string="Separator Format",
        required=True,
        default="[3,0]",
        help="The International Grouping will represent 123456789 to be 123,456,789.00; "
        "The Indian Grouping will represent 123456789 to be 12,34,56,789.00",
    )
    decimal_point = fields.Char(
        string="Decimal Separator", required=True, default=".", trim=False
    )
    thousands_sep = fields.Char(string="Thousands Separator", default=",", trim=False)

    @api.depends("code", "flag_image")
    def _compute_field_flag_image_url(self) -> None:
        """Point at the uploaded flag if there is one, else at the country flag.

        Existence is read under ``bin_size``. ``flag_image`` is an
        attachment-backed Image, so asking for it plainly fetches every
        language's image and base64-encodes it to answer a yes/no — and
        ``flag_image_url`` is in :attr:`CACHED_FIELDS`, so that ran on every cold
        warm-up of the language cache. The ORM reads ``file_size`` instead, and
        ``human_size`` maps 0 to ``False``, so truthiness is unchanged.
        """
        has_flag = set(self.with_context(bin_size=True).filtered("flag_image")._ids)
        for lang in self:
            if lang.id in has_flag:
                lang.flag_image_url = f"/web/image/res.lang/{lang.id}/flag_image"
            elif not lang.code:
                lang.flag_image_url = False
            else:
                country_code = lang.code.lower().rsplit("_")[-1]
                if country_code.isdigit() or "_" not in lang.code:
                    country_code = lang.code.lower().split("_")[0]
                lang.flag_image_url = (
                    f"/base/static/img/country_flags/{country_code}.png"
                )

    flag_image = fields.Image("Image")
    flag_image_url = fields.Char(compute=_compute_field_flag_image_url)

    _name_uniq = models.Constraint(
        "unique(name)",
        "The name of the language must be unique!",
    )
    _code_uniq = models.Constraint(
        "unique(code)",
        "The code of the language must be unique!",
    )
    _url_code_uniq = models.Constraint(
        "unique(url_code)",
        "The URL code of the language must be unique!",
    )

    @api.constrains("active")
    def _check_active(self) -> None:
        if self.env.registry.ready and not self.search_count([("active", "=", True)]):
            raise ValidationError(_("At least one language must be active."))

    @api.constrains("time_format", "date_format")
    def _check_format(self) -> None:
        for lang in self:
            for pattern in lang._disallowed_datetime_patterns:
                if (lang.time_format and pattern in lang.time_format) or (
                    lang.date_format and pattern in lang.date_format
                ):
                    raise ValidationError(
                        _(
                            "Invalid date/time format directive specified. "
                            "Please refer to the list of allowed directives, "
                            "displayed when you edit a language."
                        )
                    )

    @api.onchange("time_format", "date_format")
    def _onchange_format(self) -> dict[str, Any] | None:
        warning = {
            "warning": {
                "title": _("Using 24-hour clock format with AM/PM can cause issues."),
                "message": _("Changing to 12-hour clock format instead."),
                "type": "notification",
            }
        }
        for lang in self:
            if (
                lang.date_format
                and "%H" in lang.date_format
                and "%p" in lang.date_format
            ):
                lang.date_format = lang.date_format.replace("%H", "%I")
                return warning
            if (
                lang.time_format
                and "%H" in lang.time_format
                and "%p" in lang.time_format
            ):
                lang.time_format = lang.time_format.replace("%H", "%I")
                return warning
        return None

    def _register_hook(self) -> None:
        if not self.search_count([]):
            _logger.error("No language is active.")

    def _find_lang_by_code(self, code: str) -> Self:
        """Return the (possibly inactive) language record matching ``code``,
        or an empty recordset.
        """
        return self.with_context(active_test=False).search([("code", "=", code)])

    def _activate_lang(self, code: str) -> Self:
        """Activate the language matching ``code`` without loading translations."""
        lang = self._find_lang_by_code(code)
        if lang and not lang.active:
            lang.active = True
        return lang

    def _activate_and_install_lang(self, code: str) -> Self:
        """Activate the language matching ``code`` and load its translations.

        Unlike :meth:`_activate_lang`, this routes through
        :meth:`action_unarchive`, which also triggers ``_update_translations``.
        """
        lang = self._find_lang_by_code(code)
        if lang and not lang.active:
            lang.action_unarchive()
        return lang

    def _create_lang(self, lang: str, lang_name: str | None = None) -> Self:
        """Create the given language and make it active."""
        iso_lang = tools.get_iso_codes(lang)
        if not lang_name:
            lang_name = lang

        def fix_datetime_format(format):
            """Map libc-specific strftime directives to the always-available
            C89 ones, for cross-platform format strings."""
            format = format.replace("%-", "%")
            for pattern, replacement in tools.misc.DATETIME_FORMATS_MAP.items():
                format = format.replace(pattern, replacement)
            return str(format)

        with _LOCALE_LOCK:
            try:
                fail = True
                for ln in tools.translate.get_locales(lang):
                    try:
                        locale.setlocale(locale.LC_ALL, str(ln))
                        fail = False
                        break
                    except locale.Error:
                        continue
                if fail:
                    lc = locale.getlocale()[0]
                    msg = "Unable to get information for locale %s. Information from the default locale (%s) have been used."
                    _logger.warning(msg, lang, lc)

                conv = locale.localeconv()
                grouping = str(conv.get("grouping") or "[3,0]").replace(" ", "")
                grouping_options = {v for v, _ in self._fields["grouping"].selection}
                lang_info = {
                    "code": lang,
                    "iso_code": iso_lang,
                    "name": lang_name,
                    "active": True,
                    "date_format": fix_datetime_format(
                        locale.nl_langinfo(locale.D_FMT)
                    ),
                    "time_format": fix_datetime_format(
                        locale.nl_langinfo(locale.T_FMT)
                    ),
                    "decimal_point": str(conv["decimal_point"]),
                    "thousands_sep": str(conv["thousands_sep"]),
                    "grouping": grouping if grouping in grouping_options else "[3,0]",
                }
            finally:
                tools.translate.resetlocale()
        return self.create(lang_info)

    @api.model
    def install_lang(self) -> bool:
        """Load the default language and set it as the default partner language."""
        lang_code = (tools.config.get("load_language") or "en_US").split(",")[0]
        self._activate_lang(lang_code) or self._create_lang(lang_code)
        IrDefault = self.env["ir.default"]
        default_value = IrDefault._get("res.partner", "lang")
        if default_value is None:
            IrDefault.set("res.partner", "lang", lang_code)
            partner = self.env.company.partner_id
            if not partner.lang:
                partner.write({"lang": lang_code})
        return True

    CACHED_FIELDS = OrderedSet(
        [
            "id",
            "name",
            "code",
            "iso_code",
            "url_code",
            "active",
            "direction",
            "date_format",
            "time_format",
            "week_start",
            "grouping",
            "decimal_point",
            "thousands_sep",
            "flag_image_url",
        ]
    )

    def _get_data(self, **kwargs) -> LangData:
        """Return the LangData for a single ``{field_name: field_value}`` pair.

        E.g. ``_get_data(code='en_US')``. Prefer a cached ``field_name`` ('id',
        'code', 'url_code'). Returns a dummy LangData (all ``CACHED_FIELDS`` are
        ``False``) when no **active** language matches.

        :raise UserError: if ``field_name`` is not in ``self.CACHED_FIELDS``
        """
        if len(kwargs) != 1:
            raise TypeError(
                f"_get_data() requires exactly one keyword argument, got {len(kwargs)}"
            )
        [[field_name, field_value]] = kwargs.items()
        return self._get_active_by(field_name)[field_value]

    def _lang_get(self, code: str) -> Self:
        """Return the language using this code if it is active"""
        return self.browse(self._get_data(code=code).id)

    def _get_code(self, code: str) -> str | Literal[False]:
        """Return the given language code if active, else return ``False``"""
        return self._get_data(code=code).code

    @api.model
    @api.readonly
    def get_installed(self) -> list[tuple[str, str]]:
        """Return installed languages' (code, name) pairs sorted by name."""
        return [(code, data.name) for code, data in self._get_active_by("code").items()]

    @tools.ormcache("field", cache="stable")
    def _get_active_by(self, field: str) -> LangDataDict:
        """Return a LangDataDict mapping active languages' **unique required**
        ``self.CACHED_FIELDS`` values to their LangData, ordered by name.

        Prefer a reused ``field``: 'id', 'code', 'url_code'.
        """
        if field not in self.CACHED_FIELDS:
            raise UserError(_('Field "%s" is not cached', field))
        if field == "code":
            langs = (
                self.sudo()
                .with_context(active_test=True)
                .search_fetch([], self.CACHED_FIELDS, order="name")
            )
            return LangDataDict(
                {
                    lang.code: LangData({f: lang[f] for f in self.CACHED_FIELDS})
                    for lang in langs
                }
            )
        return LangDataDict(
            {data[field]: data for data in self._get_active_by("code").values()}
        )

    def action_unarchive(self) -> bool:
        activated = self.filtered(lambda rec: not rec.active)
        res = super(ResLang, activated).action_unarchive()
        if activated:
            active_lang = activated.mapped("code")
            mods = self.env["ir.module.module"].search([("state", "=", "installed")])
            mods._update_translations(active_lang)
        return res

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        self.env.registry.clear_cache("stable")
        for vals in vals_list:
            if not vals.get("url_code"):
                vals["url_code"] = vals.get("iso_code") or vals["code"]
        return super().create(vals_list)

    def write(self, vals: dict[str, Any]) -> bool:
        lang_codes = self.mapped("code")
        if "code" in vals and any(code != vals["code"] for code in lang_codes):
            raise UserError(_("Language code cannot be modified."))
        if "active" in vals and not vals["active"]:
            if (
                self.env["res.users"]
                .with_context(active_test=True)
                .search_count([("lang", "in", lang_codes)], limit=1)
            ):
                raise UserError(
                    _("Cannot deactivate a language that is currently used by users.")
                )
            if (
                self.env["res.partner"]
                .with_context(active_test=True)
                .search_count([("lang", "in", lang_codes)], limit=1)
            ):
                raise UserError(
                    _(
                        "Cannot deactivate a language that is currently used by contacts."
                    )
                )
            if (
                self.env["res.users"]
                .with_context(active_test=False)
                .search_count([("lang", "in", lang_codes)], limit=1)
            ):
                raise UserError(
                    _(
                        "You cannot archive the language in which Odoo was setup as it is used by automated processes."
                    )
                )
            if (
                self.env["res.partner"]
                .with_context(active_test=False)
                .search_count([("lang", "in", lang_codes)], limit=1)
            ):
                raise UserError(
                    _(
                        "Cannot deactivate a language that is used by archived contacts. "
                        "Reactivating those contacts would leave them with an inactive language."
                    )
                )
            self.env["ir.default"].discard_values("res.partner", "lang", lang_codes)

        res = super().write(vals)

        if vals.get("active"):
            for long_lang in self.filtered(lambda lang: "_" in lang.url_code):
                short_code = long_lang.code.split("_")[0]
                short_lang = self.with_context(active_test=False).search(
                    [
                        ("url_code", "=", short_code),
                    ],
                    limit=1,
                )
                if (
                    short_lang
                    and not short_lang.active
                    and short_lang.code != short_code
                ):
                    short_lang.url_code = short_lang.code
                    long_lang.url_code = short_code

        self.env.flush_all()
        self.env.registry.clear_cache("stable")
        return res

    @api.ondelete(at_uninstall=True)
    def _unlink_except_default_lang(self) -> None:
        for language in self:
            if language.code == "en_US":
                raise UserError(_("Base Language 'en_US' can not be deleted."))
            ctx_lang = self.env.context.get("lang")
            if ctx_lang and (language.code == ctx_lang):
                raise UserError(
                    _(
                        "You cannot delete the language which is the user's preferred language."
                    )
                )
            if language.active:
                raise UserError(
                    _(
                        "You cannot delete the language which is Active!\nPlease de-activate the language first."
                    )
                )

    def unlink(self) -> bool:
        self.env.registry.clear_cache("stable")
        return super().unlink()

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for record, vals in zip(self, vals_list, strict=True):
            if "name" not in default:
                vals["name"] = _("%s (copy)", record.name)
            if "code" not in default:
                vals["code"] = self._get_unique_copy_value("code", record.code)
            if "url_code" not in default:
                vals["url_code"] = self._get_unique_copy_value(
                    "url_code", record.url_code
                )
        return vals_list

    def _get_unique_copy_value(self, fname: str, value: str) -> str:
        """Return a URL-safe copy suffix of ``value`` unique for ``fname``.

        Tries ``<value>_copy`` first, then ``<value>_copy2``, ``_copy3``, …
        until the candidate is free (``fname`` carries a unique constraint).
        """
        Lang = self.with_context(active_test=False)
        candidate = f"{value}_copy"
        counter = 2
        while Lang.search_count([(fname, "=", candidate)], limit=1):
            candidate = f"{value}_copy{counter}"
            counter += 1
        return candidate

    def format(self, percent: str, value, grouping: bool = False) -> str:
        """Format ``value`` using the ``percent`` ``%char`` specifier with this
        language's locale.

        Thin registry-facing wrapper around the pure :func:`format_number`: it
        only resolves this record's :class:`LangData` and checks the language is
        installed. Callers that already hold a ``LangData`` (e.g. ``formatLang``)
        should call :func:`format_number` directly to skip the cache hops.
        """
        self.ensure_one()
        data = self._get_data(id=self.id)
        if not data:
            raise UserError(_("The language %s is not installed.", self.name))
        return format_number(percent, value, data, grouping=grouping)

    def action_activate_langs(self) -> dict[str, Any]:
        """Activate the selected languages"""
        self.action_unarchive()
        message = _(
            "The languages that you selected have been successfully installed. Users can choose their favorite language in their preferences."
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "target": "new",
            "params": {
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
