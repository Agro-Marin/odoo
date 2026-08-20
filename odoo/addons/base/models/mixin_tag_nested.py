import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.base.models.mixin_catalog import name_uniq_index

_CODE_SEPARATORS = re.compile(r"[^A-Z0-9]+")


class MixinTagNested(models.AbstractModel):
    """A tag that nests: parent, children, and a path for a display name.

    Everything :class:`mixin.tag` gives, plus the hierarchy — so a model opts
    into a tree by asking for one, rather than by inheriting the word "tag".

    The inheriting model declares its own ``parent_id`` and ``child_ids``,
    because a self-reference cannot name its comodel from here.

    Name uniqueness is re-scoped to the parent: two branches may each hold a
    "North", which is the point of a tree, and the flat rule would refuse the
    second. The derived declaration replaces the inherited one under the same
    attribute name — see :class:`mixin.catalog` for why that is the supported
    way to change it. ``code`` stays globally unique regardless: identity is
    not a per-branch question.
    """

    _name = "mixin.tag.nested"
    _inherit = ["mixin.tag"]
    _description = "Nested Tag (tag with a parent/child hierarchy)"
    _parent_store = True

    parent_path = fields.Char(index=True)

    _name_src_uniq = name_uniq_index(
        "parent_id",
        message="A tag with this name already exists under the same parent.",
    )

    @api.constrains("parent_id")
    def _check_parent_id(self):
        if self._has_cycle():
            raise ValidationError(_("You can not create recursive tags."))

    @api.depends("name", "parent_id.name")
    def _compute_display_name(self):
        paths = {}
        ancestor_ids = set()
        for tag in self:
            if tag.parent_path:
                paths[tag.id] = ids = [
                    int(key) for key in tag.parent_path.split("/") if key
                ]
                ancestor_ids.update(ids)
        ancestors = self.browse(ancestor_ids)
        ancestors.fetch(["name"])
        names = {tag.id: tag.name or "" for tag in ancestors}

        for tag in self:
            path_ids = paths.get(tag.id)
            if path_ids is not None:
                tag.display_name = " / ".join(names[key] for key in path_ids)
                continue
            walked = []
            seen = set()
            current = tag
            while current and current.id not in seen:
                seen.add(current.id)
                walked.append(current.name or "")
                current = current.parent_id
            tag.display_name = " / ".join(reversed(walked))

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if operator.endswith("like"):
            if operator.startswith("not"):
                return NotImplemented
            return [("id", "child_of", tuple(self._search(domain)))]
        return domain
