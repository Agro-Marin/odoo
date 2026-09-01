import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .mixin_catalog import name_uniq_index

_NON_ALPHANUMERIC = re.compile(r"[^0-9A-Za-z]+")


class ResPartnerIdentifierType(models.Model):
    """A kind of identifier a contact can carry: RFC, CURP, SIREN, GLN…

    The dimension only. What a given contact's identifier *is* lives in
    ``res.partner.identifier``, one row per contact per type, because an
    identifier's value is free text unique to its holder rather than a choice
    from a shared vocabulary. That is the one point where this family departs
    from ``mixin.attribute``, whose value model is a catalog several subjects
    select from.
    """

    _name = "res.partner.identifier.type"
    _inherit = ["mixin.catalog"]
    _description = "Partner Identifier Type"
    _order = "sequence, name"

    code = fields.Char(
        required=True,
        help="Stable key this type is resolved by. Localizations and "
        "integrations name the code, never the label, which is translated "
        "and editable.",
    )
    sequence = fields.Integer(
        default=10,
    )
    country_ids = fields.Many2many(
        comodel_name="res.country",
        string="Countries",
        help="Offer this identifier only for contacts in these countries. "
        "Leave empty to offer it everywhere.",
    )
    pattern = fields.Char(
        string="Format",
        help="Optional regular expression the normalized value must match, "
        "anchored at both ends. Checked before any code-specific rule.",
    )
    unique_across_contacts = fields.Boolean(
        default=True,
        help="Refuse a value another contact already carries under this type. "
        "Turn it off for an identifier that is legitimately shared, such as a "
        "group-wide registration.",
    )
    multiple_per_contact = fields.Boolean(
        default=False,
        help="Allow one contact to carry several values of this type.",
    )
    confidential = fields.Boolean(
        default=False,
        help="Restrict this identifier to its own holder and to the groups "
        "granted full access by a record rule. Use it for what identifies a "
        "person to the state -- a national number, a passport -- and leave it "
        "off for what a company publishes about itself, such as a tax ID.",
    )
    synced_with_commercial = fields.Boolean(
        default=False,
        help="Copy this identifier from the commercial entity down to its "
        "contacts. Use it for what identifies the *company* -- a tax ID -- and "
        "leave it off for what identifies a person, such as a national number.",
    )

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        "An identifier type with this code already exists.",
    )
    _name_src_uniq = name_uniq_index(
        message="An identifier type with this name already exists.",
    )

    @api.constrains("pattern")
    def _check_pattern_compiles(self):
        for identifier_type in self:
            if not identifier_type.pattern:
                continue
            try:
                re.compile(identifier_type.pattern)
            except re.error as error:
                raise ValidationError(
                    self.env._(
                        "%(name)s: the format is not a valid regular "
                        "expression (%(error)s).",
                        name=identifier_type.display_name,
                        error=error,
                    )
                ) from error

    @api.model
    def _normalize(self, value):
        """Strip punctuation and case so two spellings compare equal.

        Identifiers are written with spaces, dots and dashes that carry no
        information: `RIFE001128IT2` and `RIFE-001128-IT2` are one value. The
        stored `value` keeps whatever was typed; comparison and uniqueness use
        this.
        """
        return _NON_ALPHANUMERIC.sub("", value or "").upper()

    def validate(self, value):
        """Check `value` against this type, raising ValidationError if it fails.

        Three stages, cheapest first: the format, then a rule named after the
        code, then whatever a localization adds by overriding `_check_hook`.
        The code-specific rule is looked up as `_check_<code>` on this model,
        the same dispatch `account_vat` uses for `check_vat_xx`, so a
        localization adds one method instead of editing this one.

        :return: the normalized value
        """
        self.check_singleton()
        normalized = self._normalize(value)
        if not normalized:
            raise ValidationError(
                self.env._(
                    "%(name)s cannot be empty.", name=self.display_name
                )
            )
        if self.pattern and not re.fullmatch(self.pattern, normalized):
            raise ValidationError(
                self.env._(
                    "%(value)s is not a valid %(name)s.",
                    value=value,
                    name=self.display_name,
                )
            )
        checker = getattr(self, f"_check_{(self.code or '').lower()}", None)
        if checker and not checker(normalized):
            raise ValidationError(
                self.env._(
                    "%(value)s is not a valid %(name)s.",
                    value=value,
                    name=self.display_name,
                )
            )
        self._check_hook(normalized)
        return normalized

    def _check_hook(self, normalized):
        """Extension point for rules that need more than a true/false answer."""

    @api.model
    def _by_code(self, code):
        """Resolve a type by its stable code, or an empty recordset."""
        return self.search([("code", "=", code)], limit=1)
