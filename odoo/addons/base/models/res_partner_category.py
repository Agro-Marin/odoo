from random import randint

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartnerCategory(models.Model):
    _name = "res.partner.category"
    _description = "Partner Tags"
    _order = "name, id"
    _parent_store = True

    def _get_default_color(self) -> int:
        return randint(1, 11)

    name = fields.Char("Name", required=True, translate=True)
    color = fields.Integer(string="Color", default=_get_default_color, aggregator=False)
    parent_id: ResPartnerCategory = fields.Many2one(
        "res.partner.category",
        string="Category",
        index=True,
        ondelete="cascade",
    )
    child_ids: ResPartnerCategory = fields.One2many(
        "res.partner.category", "parent_id", string="Child Tags"
    )
    active = fields.Boolean(
        default=True,
        help="The active field allows you to hide the category without removing it.",
    )
    parent_path = fields.Char(index=True)
    partner_ids = fields.Many2many(
        "res.partner",
        column1="category_id",
        column2="partner_id",
        string="Partners",
        copy=False,
    )

    @api.constrains("parent_id")
    def _check_parent_id(self) -> None:
        if self._has_cycle():
            raise ValidationError(_("You can not create recursive tags."))

    @api.depends("name", "parent_id.name")
    def _compute_display_name(self) -> None:
        """Compute the slash-joined full ancestor path as display name."""
        names = {category.id: [] for category in self}
        # Walk the hierarchy one level at a time, advancing every category's
        # cursor together. Reading name on the whole frontier prefetches the
        # level in a single query instead of one read per category, while
        # preserving the per-record walk semantics.
        cursors = {category.id: category for category in self}
        while cursors:
            frontier = self.browse().union(*cursors.values())
            frontier.fetch(["name", "parent_id"])
            next_cursors = {}
            for root_id, current in cursors.items():
                names[root_id].append(current.name or "")
                if current.parent_id:
                    next_cursors[root_id] = current.parent_id
            cursors = next_cursors
        for category in self:
            category.display_name = " / ".join(reversed(names[category.id]))

    @api.model
    def _search_display_name(self, operator: str, value: str) -> list:
        domain = super()._search_display_name(operator, value)
        if operator.endswith("like"):
            if operator.startswith("not"):
                return NotImplemented
            return [("id", "child_of", tuple(self._search(domain)))]
        return domain
