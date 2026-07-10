import logging
import re
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import DomainType, ValuesType
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


FLAG_MAPPING = {
    "GF": "fr",
    "BV": "no",
    "BQ": "nl",
    "GP": "fr",
    "HM": "au",
    "YT": "fr",
    "RE": "fr",
    "MF": "fr",
    "UM": "us",
    "XI": "uk",
}

NO_FLAG_COUNTRIES = [
    "AQ",  # Antarctica
    "SJ",  # Svalbard + Jan Mayen : separate jurisdictions : no dedicated flag
]


class ResCountry(models.Model):
    _name = "res.country"
    _description = "Country"
    _order = "name, id"
    _rec_names_search = ["name", "code"]

    name = fields.Char(string="Country Name", required=True, translate=True)
    code = fields.Char(
        string="Country Code",
        size=2,
        required=True,
        help="The ISO country code in two chars. \nYou can use this field for quick search.",
    )
    address_format = fields.Text(
        string="Layout in Reports",
        help="Display format to use for addresses belonging to this country.\n\n"
        "You can use python-style string pattern with all the fields of the address "
        "(for example, use '%(street)s' to display the field 'street') plus"
        "\n%(state_name)s: the name of the state"
        "\n%(state_code)s: the code of the state"
        "\n%(country_name)s: the name of the country"
        "\n%(country_code)s: the code of the country",
        default="%(street)s\n%(street2)s\n%(city)s %(state_code)s %(zip)s\n%(country_name)s",
    )
    address_view_id = fields.Many2one(
        comodel_name="ir.ui.view",
        string="Input View",
        domain=[("model", "=", "res.partner"), ("type", "=", "form")],
        help="Use this field if you want to replace the usual way to encode a complete address. "
        "Note that the address_format field is used to modify the way to display addresses "
        "(in reports for example), while this field is used to modify the input form for "
        "addresses.",
    )
    currency_id = fields.Many2one("res.currency", string="Currency")
    image_url = fields.Char(
        compute="_compute_image_url",
        string="Flag",
        help="Url of static flag image",
    )
    phone_code = fields.Integer(string="Country Calling Code")
    country_group_ids = fields.Many2many(
        "res.country.group",
        "res_country_res_country_group_rel",
        "res_country_id",
        "res_country_group_id",
        string="Country Groups",
    )
    country_group_codes = fields.Json(compute="_compute_country_group_codes")
    state_ids = fields.One2many("res.country.state", "country_id", string="States")
    name_position = fields.Selection(
        [
            ("before", "Before Address"),
            ("after", "After Address"),
        ],
        string="Customer Name Position",
        default="before",
        help="Determines where the customer/company name should be placed, i.e. after or before the address.",
    )
    vat_label = fields.Char(
        string="Vat Label",
        translate=True,
        prefetch=True,
        help="Use this field if you want to change vat label.",
    )

    state_required = fields.Boolean(default=False)
    zip_required = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        "unique (name)",
        "The name of the country must be unique!",
    )
    _code_uniq = models.Constraint(
        "unique (code)",
        "The code of the country must be unique!",
    )

    @api.model
    def name_search(
        self,
        name: str = "",
        domain: DomainType | None = None,
        operator: str = "ilike",
        limit: int = 100,
    ) -> list[tuple[int, str]]:
        """Search countries, matching a 2-char ``name`` against ``code`` first
        so code matches rank before name matches.

        :rtype: list[tuple[int, str]]
        """
        result = []
        domain = Domain(domain or Domain.TRUE)
        # first search by code
        if operator not in Domain.NEGATIVE_OPERATORS and name and len(name) == 2:
            countries = self.search_fetch(
                domain & Domain("code", operator, name),
                ["display_name"],
                limit=limit,
            )
            # No sudo: search_fetch already permission-checked and prefetched
            # display_name; sudo would discard that prefetch.
            result.extend((country.id, country.display_name) for country in countries)
            domain &= Domain("id", "not in", countries.ids)
            if limit is not None:
                limit -= len(countries)
                if limit <= 0:
                    return result
        # normal search
        result.extend(super().name_search(name, domain, operator, limit))
        return result

    @api.model
    @tools.ormcache("code", cache="stable")
    def _phone_code_for(self, code: str) -> int:
        return self.search([("code", "=", code)]).phone_code

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        self.env.registry.clear_cache("stable")
        for vals in vals_list:
            if vals.get("code"):
                vals["code"] = vals["code"].upper()
        return super().create(vals_list)

    def write(self, vals: dict[str, Any]) -> bool:
        if vals.get("code"):
            vals["code"] = vals["code"].upper()
        res = super().write(vals)
        if "code" in vals or "phone_code" in vals:
            # _phone_code_for caches code -> phone_code; bust it when either changes.
            self.env.registry.clear_cache("stable")
        # No clear_cache("templates") for address_view_id / address_format /
        # vat_label: their view-cache consumers (format.address.mixin,
        # format.vat.label.mixin) key _get_view_cache_key on the field VALUES,
        # so a change yields a new key and stale entries are never served again.
        return res

    def unlink(self) -> bool:
        self.env.registry.clear_cache("stable")
        return super().unlink()

    def get_address_fields(self) -> list[str]:
        """Return the address placeholder names parsed from ``address_format``."""
        self.ensure_one()
        # Match only real %(field)s placeholders; a laxer \((.+?)\) would capture
        # literal parenthesized text as field names. ``address_format`` may be
        # False, so guard re.findall against a non-string value.
        return re.findall(r"%\((\w+)\)s", self.address_format or "")

    @api.depends("code")
    def _compute_image_url(self) -> None:
        for country in self:
            if not country.code or country.code in NO_FLAG_COUNTRIES:
                country.image_url = False
            else:
                code = FLAG_MAPPING.get(country.code, country.code.lower())
                country.image_url = f"/base/static/img/country_flags/{code}.png"

    @api.constrains("address_format")
    def _check_address_format(self) -> None:
        address_fields = self.env["res.partner"]._formatting_address_fields() + [
            "state_code",
            "state_name",
            "country_code",
            "country_name",
            "company_name",
        ]
        test_values = dict.fromkeys(address_fields, "test")
        for record in self:
            if record.address_format:
                try:
                    record.address_format % test_values
                # Reject TypeError too (e.g. numeric %d against string values):
                # res.partner._display_address only catches KeyError/ValueError,
                # so catch it here to avoid an uncaught TypeError at render time.
                except ValueError, KeyError, TypeError:
                    raise UserError(
                        _("The layout contains an invalid format key")
                    ) from None

    @api.depends("country_group_ids")
    def _compute_country_group_codes(self) -> None:
        """Compute the JSON list of country group codes for this country."""
        # Fall back to [""] rather than [] so the cached Json value is never
        # coerced to False and stays a valid iterable for consumers.
        for country in self:
            country.country_group_codes = [
                g.code for g in country.country_group_ids if g.code
            ] or [""]


class ResCountryGroup(models.Model):
    _name = "res.country.group"
    _description = "Country Group"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(string="Code")
    country_ids = fields.Many2many(
        "res.country",
        "res_country_res_country_group_rel",
        "res_country_group_id",
        "res_country_id",
        string="Countries",
    )

    _check_code_uniq = models.Constraint(
        "unique(code)",
        "The country group code must be unique!",
    )

    def _sanitize_vals(self, vals: dict[str, Any]) -> dict[str, Any]:
        if code := vals.get("code"):
            vals["code"] = code.upper()
        return vals

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        return super().create([self._sanitize_vals(vals) for vals in vals_list])

    def write(self, vals: dict[str, Any]) -> bool:
        return super().write(self._sanitize_vals(vals))


class ResCountryState(models.Model):
    _name = "res.country.state"
    _description = "Country state"
    _order = "code, id"
    _rec_names_search = ["name", "code"]

    country_id = fields.Many2one(
        "res.country", string="Country", required=True, index=True
    )
    name = fields.Char(
        string="State Name",
        required=True,
        help="Administrative divisions of a country. E.g. Fed. State, Department, Canton",
    )
    code = fields.Char(string="State Code", help="The state code.", required=True)

    _name_code_uniq = models.Constraint(
        "unique(country_id, code)",
        "The code of the state must be unique by country!",
    )

    @api.model
    def name_search(
        self,
        name: str = "",
        domain: DomainType | None = None,
        operator: str = "ilike",
        limit: int = 100,
    ) -> list[tuple[int, str]]:
        """Search states, matching ``name`` against ``code`` (=ilike) first so
        code matches rank before name matches.

        Also accepts the ``in`` operator by fanning out one search per item.

        :rtype: list[tuple[int, str]]
        """
        result = []
        domain = Domain(domain or Domain.TRUE)
        # accepting 'in' as operator (see odoo/addons/base/tests/test_res_country.py)
        if operator == "in":
            if limit is None:
                limit = 100  # force a limit
            for item in name:
                result.extend(
                    self.name_search(
                        item, domain, operator="=", limit=limit - len(result)
                    )
                )
                if len(result) == limit:
                    break
            return result
        # first search by code (with =ilike)
        if operator not in Domain.NEGATIVE_OPERATORS and name:
            states = self.search_fetch(
                domain & Domain("code", "=ilike", name),
                ["display_name"],
                limit=limit,
            )
            # No sudo: search_fetch already permission-checked and prefetched
            # display_name (from name and country_id.code, both readable without
            # elevation); sudo would discard that prefetch.
            result.extend((state.id, state.display_name) for state in states)
            domain &= Domain("id", "not in", states.ids)
            if limit is not None:
                limit -= len(states)
                if limit <= 0:
                    return result
        # normal search
        result.extend(super().name_search(name, domain, operator, limit))
        return result

    @api.model
    def _search_display_name(self, operator: str, value: str) -> Domain:
        domain = super()._search_display_name(operator, value)
        if value and operator not in Domain.NEGATIVE_OPERATORS:
            if operator in ("ilike", "="):
                domain |= self._get_name_search_domain(value, operator)
            elif operator == "in":
                domain |= Domain.OR(
                    self._get_name_search_domain(name, "=") for name in value
                )
        if country_id := self.env.context.get("country_id"):
            domain &= Domain("country_id", "=", country_id)
        return domain

    def _get_name_search_domain(self, name: str, operator: str) -> Domain:
        if m := re.fullmatch(r"(?P<name>.+)\((?P<country>.+)\)", name):
            return Domain(
                [
                    ("name", operator, m["name"].strip()),
                    "|",
                    ("country_id.name", "ilike", m["country"].strip()),
                    ("country_id.code", "=", m["country"].strip()),
                ]
            )
        return Domain.FALSE

    @api.depends("country_id.code")
    @api.depends_context("formatted_display_name")
    def _compute_display_name(self) -> None:
        formatted = self.env.context.get("formatted_display_name")
        for record in self:
            code = record.country_id.code
            if formatted:
                record.display_name = f"{record.name} \t --{code}--"
            else:
                record.display_name = f"{record.name} ({code})"
