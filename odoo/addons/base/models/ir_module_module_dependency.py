from odoo import api, fields, models


class IrModuleModuleDependency(models.Model):
    _name = "ir.module.module.dependency"
    _inherit = ["mixin.module.link"]
    _description = "Module dependency"
    _log_access = False

    linked_id = fields.Many2one(string="Dependency")

    auto_install_required = fields.Boolean(
        default=True,
        help="Whether this dependency blocks automatic installation of the dependent",
    )

    _module_dependency_uniq = models.Constraint(
        "UNIQUE (module_id, name)",
        "A module cannot declare the same dependency twice!",
    )

    @api.model
    def all_dependencies(self, module_names: list[str]) -> dict[str, list[str]]:
        searched: set[str] = set()
        to_search = set(module_names)
        res: dict[str, list[str]] = {}
        while to_search:
            searched |= to_search
            groups = self._read_group(
                [("module_id.name", "in", list(to_search))],
                groupby=["module_id"],
                aggregates=["name:array_agg"],
            )
            to_search.clear()
            for module, dep_names in groups:
                res[module.name] = dep_names
                to_search.update(set(dep_names) - searched)
        return res
