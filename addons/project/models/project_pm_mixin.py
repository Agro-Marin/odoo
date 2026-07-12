"""Shared mixin for the small project-scoped PM configuration models.

Several fork-added models (project.role, project.triage, project.phase,
project.workflow.step) each repeated the exact same ``copy_data`` idiom that
appends " (copy)" to the record name on duplication. This abstract model holds
that single behaviour so the four copies cannot drift apart.
"""

from odoo import models


class ProjectPmMixin(models.AbstractModel):
    _name = "project.pm.mixin"
    _description = "Project PM Record Mixin"

    def copy_data(self, default: dict | None = None) -> list[dict]:
        """Append '(copy)' to the ``name`` of each duplicated record."""
        vals_list = super().copy_data(default=default)
        return [
            dict(vals, name=self.env._("%s (copy)", record.name))
            for record, vals in zip(self, vals_list, strict=True)
        ]
