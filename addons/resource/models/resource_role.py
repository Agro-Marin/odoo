from random import randint

from odoo import fields, models


class ResourceRole(models.Model):
    """A capability a resource can be asked to fulfil.

    Chef, Bartender, Developer, Reviewer: a named, colour-coded, orderable
    tag that answers "what can this person do" and "what does this piece of
    work need". It lives here because that question belongs to the resource,
    not to whichever app is asking -- ``project`` and ``planning`` each grew
    their own copy of this model, field for field, and a role defined in one
    was invisible to the other even when both meant the same person.

    Deliberately *not* ``res.role`` (``mail``), which looks like the same
    thing and is not: that one is a mention group, a set of users an ``@role``
    notifies, with a unique name and no notion of capacity, colour or order.

    Uniqueness is not enforced. Neither predecessor enforced it, and live data
    is free to hold two roles of the same name; adopting ``mixin.catalog``
    (which would supply ``name``/``active`` and a uniqueness index that has to
    be explicitly declined) is a reasonable follow-up, not something to fold
    into a data migration.
    """

    _name = "resource.role"
    _description = "Resource Role"
    _order = "sequence, name, id"

    def _get_default_color(self) -> int:
        return randint(1, 11)

    active = fields.Boolean(default=True)
    name = fields.Char(required=True, translate=True)
    color = fields.Integer(default=_get_default_color)
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
