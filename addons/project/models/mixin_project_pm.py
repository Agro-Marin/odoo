"""Shared mixin for the small project-scoped PM configuration models.

Several fork-added models (project.triage, project.phase,
project.workflow.step) each repeated the exact same ``copy_data`` idiom that
appends " (copy)" to the record name on duplication. This abstract model holds
that single behaviour so the copies cannot drift apart.
"""

from odoo import models
from odoo.api import ValuesType


class MixinProjectPm(models.AbstractModel):
    _name = "mixin.project.pm"
    _description = "Project PM Record Mixin"

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        """Append '(copy)' to the ``name`` of each duplicated record."""
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
