from random import randint

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TagMixin(models.AbstractModel):
    """Shared behaviour for hierarchical, colored tags.

    Concrete models mixing this in MUST declare the self-referential hierarchy
    fields with their own ``_name`` as comodel -- an abstract model has no table
    and therefore cannot be the comodel of ``parent_id`` / ``child_ids``::

        parent_id = fields.Many2one(<model>, ondelete="cascade", index=True)
        child_ids = fields.One2many(<model>, "parent_id")
    """

    _name = "tag.mixin"
    _description = "Tag Mixin"
    _order = "name, id"
    _parent_store = True

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char(string="Tag Name", required=True, translate=True)
    active = fields.Boolean(
        default=True,
        help="Archive a tag to hide it without deleting it.",
    )
    color = fields.Integer(
        string="Color",
        default=_get_default_color,
        aggregator=False,
    )
    parent_path = fields.Char(index=True)

    @api.constrains("parent_id")
    def _check_parent_id(self):
        if self._has_cycle():
            raise ValidationError(_("You can not create recursive tags."))

    @api.depends("name", "parent_id.name")
    def _compute_display_name(self):
        """Compute the slash-joined full ancestor path as display name."""
        names = {tag.id: [] for tag in self}
        # Walk the hierarchy one level at a time, advancing every tag's cursor
        # together. Reading name on the whole frontier prefetches the level in a
        # single query instead of one read per tag, while preserving the
        # per-record walk semantics.
        cursors = {tag.id: tag for tag in self}
        while cursors:
            frontier = self.browse().union(*cursors.values())
            frontier.fetch(["name", "parent_id"])
            next_cursors = {}
            for root_id, current in cursors.items():
                names[root_id].append(current.name or "")
                if current.parent_id:
                    next_cursors[root_id] = current.parent_id
            cursors = next_cursors
        for tag in self:
            tag.display_name = " / ".join(reversed(names[tag.id]))

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if operator.endswith("like"):
            if operator.startswith("not"):
                return NotImplemented
            return [("id", "child_of", tuple(self._search(domain)))]
        return domain
