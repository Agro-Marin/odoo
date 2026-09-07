import re
from collections import defaultdict
from typing import Self

from odoo import api, fields, models
from odoo.api import ValuesType

PHONE_NOISE_PATTERN = re.compile(r"[\s\\./\(\)\-]")

PHONE_TYPES = [
    ("mobile", "Mobile"),
    ("landline", "Landline"),
    ("fax", "Fax"),
    ("whatsapp", "WhatsApp"),
    ("emergency", "Emergency"),
]


class PhoneNumber(models.Model):
    _name = "phone.number"
    _description = "Phone Number"
    _order = "primary desc, sequence, id"
    _rec_name = "number"
    _rec_names_search = ["number", "sanitized", "label"]

    number = fields.Char(required=True)
    sanitized = fields.Char(
        compute="_compute_sanitized",
        store=True,
        index=True,
        readonly=True,
    )
    type = fields.Selection(PHONE_TYPES, required=True, default="mobile")
    country_id = fields.Many2one("res.country", string="Country")
    primary = fields.Boolean(default=False)
    sequence = fields.Integer(default=10)
    label = fields.Char()
    note = fields.Text()
    active = fields.Boolean(default=True)
    partner_ids = fields.Many2many(
        "res.partner",
        "res_partner_phone_number_rel",
        "phone_number_id",
        "partner_id",
        string="Contacts",
    )

    _unique_sanitized = models.Constraint(
        "unique(sanitized)",
        "This phone number already exists.",
    )

    @api.model
    def _sanitize_number(self, number: str, country=None) -> str:
        number = PHONE_NOISE_PATTERN.sub("", number or "")
        if number.startswith("00"):
            number = "+" + number[2:]
        return number

    def _phone_country(self):
        return self.country_id or self.partner_ids[:1].country_id

    @api.depends("number", "country_id", "partner_ids.country_id")
    def _compute_sanitized(self) -> None:
        for phone in self:
            phone.sanitized = self._sanitize_number(
                phone.number, phone._phone_country()
            )

    @api.depends("number", "label", "type")
    def _compute_display_name(self) -> None:
        for phone in self:
            phone.display_name = (
                f"{phone.number} ({phone.label})" if phone.label else phone.number
            )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        wanted = []
        for vals in vals_list:
            country = (
                self.env["res.country"].browse(vals["country_id"])
                if vals.get("country_id")
                else None
            )
            wanted.append(self._sanitize_number(vals.get("number"), country))
        existing = {
            phone.sanitized: phone
            for phone in self.with_context(active_test=False).search(
                [("sanitized", "in", [s for s in wanted if s])]
            )
        }
        to_create, by_position = [], {}
        for position, (vals, sanitized) in enumerate(
            zip(vals_list, wanted, strict=True)
        ):
            if phone := existing.get(sanitized):
                phone._link_existing(vals)
                by_position[position] = phone
            else:
                to_create.append((position, vals))
                existing[sanitized] = None
        created = super().create([vals for _, vals in to_create])
        for (position, _), phone in zip(to_create, created, strict=True):
            by_position[position] = phone
        return self.browse(by_position[i].id for i in range(len(vals_list)))

    def _link_existing(self, vals: ValuesType) -> None:
        relational = {
            fname: value
            for fname, value in vals.items()
            if self._fields[fname].type == "many2many"
        }
        if not self.active:
            relational["active"] = True
        if relational:
            self.write(relational)

    def _by_type(self) -> dict[str, Self]:
        grouped = defaultdict(self.browse)
        for phone in self:
            grouped[phone.type] |= phone
        return grouped

    def _primary(self, *types: str) -> Self:
        candidates = (
            self.filtered(lambda p: p.type in types) if types else self
        ) or self
        return candidates[:1]
