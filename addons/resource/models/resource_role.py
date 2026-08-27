from random import randint

from odoo import fields, models


class ResourceRole(models.Model):
    """A capability a resource can be asked to fulfil."""

    _name = "resource.role"
    _description = "Resource Role"
    _order = "sequence, name, id"

    def _default_color(self) -> int:
        return randint(1, 11)

    active = fields.Boolean(default=True)
    name = fields.Char(required=True, translate=True)
    color = fields.Integer(default=_default_color)
    sequence = fields.Integer(export_string_translation=False)

    def copy_data(self, default=None):
        """Append '(copy)' to the name of each duplicated role."""
        vals_list = super().copy_data(default=default)
        return [
            dict(vals, name=self.env._("%s (copy)", record.name))
            for record, vals in zip(self, vals_list, strict=True)
        ]

    def copy_translations(self, new, excluded=()):
        # ``copy_data`` renames ``name`` in the duplicating user's language
        # only; without this the copy would keep the source record's exact
        # ``name`` in every other language.
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )
