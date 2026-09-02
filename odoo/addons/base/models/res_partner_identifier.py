from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartnerIdentifier(models.Model):
    """One identifier a contact carries: this type, this value.

    The value is free text belonging to one contact, which is why this is not
    a ``mixin.attribute.value``: that model is a vocabulary several subjects
    select from, name-unique within its attribute and reachable by Many2many.
    Two contacts pointing at one identifier row is precisely what duplicate
    detection exists to find, so it must not be expressible.
    """

    _name = "res.partner.identifier"
    _description = "Partner Identifier"
    _order = "type_id, id"
    _rec_name = "value"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        required=True,
        ondelete="cascade",
        index=True,
    )
    type_id = fields.Many2one(
        comodel_name="res.partner.identifier.type",
        string="Type",
        required=True,
        ondelete="restrict",
        index=True,
    )
    value = fields.Char(
        required=True,
        help="As it is written on the document. Comparison ignores case and "
        "punctuation.",
    )
    normalized_value = fields.Char(
        compute="_compute_normalized_value",
        store=True,
        index=True,
        help="Punctuation and case removed, so two spellings of one identifier "
        "compare and deduplicate as one.",
    )
    company_id = fields.Many2one(
        related="partner_id.company_id",
        store=True,
        index="btree_not_null",
    )

    _type_value_index = models.Index("(type_id, normalized_value)")

    @api.depends("value")
    def _compute_normalized_value(self):
        normalize = self.env["res.partner.identifier.type"]._normalize
        for identifier in self:
            identifier.normalized_value = normalize(identifier.value)

    @api.depends("type_id", "value")
    def _compute_display_name(self):
        for identifier in self:
            identifier.display_name = f"{identifier.type_id.name}: {identifier.value}"

    @api.constrains("type_id", "value")
    def _check_value_is_valid(self):
        for identifier in self:
            identifier.type_id.validate(identifier.value)

    @api.constrains("partner_id", "type_id")
    def _check_one_per_contact(self):
        """One value per type per contact, unless the type allows several.

        One query for the whole recordset, not one per row: these constraints
        fire on every create, and an import of ten thousand contacts would
        otherwise issue ten thousand searches apiece.
        """
        candidates = self.filtered(lambda i: not i.type_id.multiple_per_contact)
        if not candidates:
            return
        held = defaultdict(list)
        for other in self.search(
            [
                ("partner_id", "in", candidates.partner_id.ids),
                ("type_id", "in", candidates.type_id.ids),
            ]
        ):
            held[(other.partner_id.id, other.type_id.id)].append(other.id)
        for identifier in candidates:
            key = (identifier.partner_id.id, identifier.type_id.id)
            if len(held.get(key, ())) > 1:
                raise ValidationError(
                    self.env._(
                        "%(partner)s already has a %(type)s.",
                        partner=identifier.partner_id.display_name,
                        type=identifier.type_id.display_name,
                    )
                )

    @api.constrains("type_id", "normalized_value", "partner_id")
    def _check_not_taken_by_another_contact(self):
        """Refuse a value another contact already carries under this type.

        Scoped to the commercial entity: a company and its own addresses share
        one tax ID by design, and that is not a collision. One query, for the
        reason given on `_check_one_per_contact`.
        """
        candidates = self.filtered(lambda i: i.type_id.unique_across_contacts)
        if not candidates:
            return
        identifier_sudo = self.sudo()
        holders = defaultdict(identifier_sudo.browse)
        for other in identifier_sudo.search(
            [
                ("type_id", "in", candidates.type_id.ids),
                ("normalized_value", "in", candidates.mapped("normalized_value")),
            ]
        ):
            holders[(other.type_id.id, other.normalized_value)] |= other
        for identifier in candidates:
            commercial = identifier.partner_id.commercial_partner_id
            taken = holders[
                (identifier.type_id.id, identifier.normalized_value)
            ].filtered(
                lambda other, commercial=commercial, identifier=identifier: (
                    other != identifier
                    and other.partner_id.commercial_partner_id != commercial
                )
            )
            if taken:
                raise ValidationError(
                    self.env._(
                        "%(value)s is already the %(type)s of %(other)s.",
                        value=identifier.value,
                        type=identifier.type_id.display_name,
                        other=taken[0].partner_id.display_name,
                    )
                )
