from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SpreadsheetDashboardGroup(models.Model):
    _name = "spreadsheet.dashboard.group"
    _description = "Group of dashboards"
    _order = "sequence"

    name = fields.Char(required=True, translate=True)
    dashboard_ids = fields.One2many("spreadsheet.dashboard", "dashboard_group_id")
    published_dashboard_ids = fields.One2many(
        "spreadsheet.dashboard",
        "dashboard_group_id",
        domain=[("is_published", "=", True)],
    )
    sequence = fields.Integer()

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        if "name" not in default:
            for group, vals in zip(self, vals_list, strict=True):
                vals["name"] = _("%s (copy)", group.name)
        return vals_list

    def copy_translations(self, new, excluded=()):
        # ``copy_data`` renames ``name`` in the duplicating user's language
        # only; without this the copy would keep the source record's exact
        # ``name`` in every other language.
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_spreadsheet_data(self):
        external_ids = self.get_external_id()
        for group in self:
            external_id = external_ids[group.id]
            if external_id and not external_id.startswith("__export__"):
                raise UserError(
                    _(
                        "You cannot delete %s as it is used in another module.",
                        group.name,
                    )
                )
