from random import randint

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TagMixin(models.AbstractModel):
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
