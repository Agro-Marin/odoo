from typing import Any, Self

import odoo
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_module import assert_log_admin_access


class BaseModuleUpgrade(models.TransientModel):
    _name = "base.module.upgrade"
    _description = "Upgrade Module"

    @api.model
    def _get_pending_modules(self) -> Self:
        """Return modules in state ``to upgrade`` / ``to remove`` / ``to install``."""
        states = ["to upgrade", "to remove", "to install"]
        return self.env["ir.module.module"].search([("state", "in", states)])

    @api.model
    def get_module_list(self) -> Self:
        # Public alias kept for RPC/external callers.
        return self._get_pending_modules()

    @api.model
    def _default_module_info(self) -> str:
        return "\n".join(
            f"{mod.name}: {mod.state}" for mod in self._get_pending_modules()
        )

    module_info = fields.Text(
        "Apps to Update", readonly=True, default=_default_module_info
    )

    @api.model
    def get_view(
        self,
        view_id: int | None = None,
        view_type: str = "form",
        **options: Any,
    ) -> dict[str, Any]:
        res = super().get_view(view_id, view_type, **options)
        if view_type != "form":
            return res

        if not self._get_pending_modules():
            res["arch"] = """<form string="Upgrade Completed">
                                <separator string="Upgrade Completed" colspan="4"/>
                                <footer>
                                    <button name="config" string="Start Configuration" type="object" class="btn-primary" data-hotkey="q"/>
                                    <button special="cancel" data-hotkey="x" string="Close" class="btn-secondary"/>
                                </footer>
                             </form>"""

        return res

    def upgrade_module_cancel(self) -> dict[str, str]:
        Module = self.env["ir.module.module"]
        # Revert the schedule: modules flagged for upgrade/removal were
        # installed beforehand, and modules flagged for install were
        # uninstalled beforehand.
        to_revert_installed = Module.search(
            [("state", "in", ["to upgrade", "to remove"])]
        )
        to_revert_installed.write({"state": "installed"})
        to_revert_uninstalled = Module.search([("state", "=", "to install")])
        to_revert_uninstalled.write({"state": "uninstalled"})
        return {"type": "ir.actions.act_window_close"}

    @assert_log_admin_access
    def upgrade_module(self) -> dict[str, str]:
        Module = self.env["ir.module.module"]

        # install/upgrade: double-check preconditions
        mods = Module.search([("state", "in", ["to upgrade", "to install"])])
        if mods:
            query = """ SELECT d.name
                        FROM ir_module_module m
                        JOIN ir_module_module_dependency d ON (m.id = d.module_id)
                        LEFT JOIN ir_module_module m2 ON (d.name = m2.name)
                        WHERE m.id = any(%s) and (m2.state IS NULL or m2.state = %s) """
            self.env.cr.execute(query, (mods.ids, "uninstalled"))
            unmet_packages = [row[0] for row in self.env.cr.fetchall()]
            if unmet_packages:
                raise UserError(
                    self.env._(
                        "The following modules are not installed or unknown: %s",
                        "\n\n" + "\n".join(unmet_packages),
                    )
                )

        # terminate transaction before re-creating cursor below
        self.env.cr.commit()
        # BMUPG-L2 (known hazard): unlike _button_immediate_function, this path
        # takes no LOCK ir_module_module / SELECT ... FOR UPDATE guards, so
        # concurrent schedule-applies (or an apply racing a triggered cron) go
        # undetected here.
        odoo.modules.registry.Registry.new(self.env.cr.dbname, update_module=True)
        self.env.cr.reset()

        return {"type": "ir.actions.act_window_close"}

    def config(self) -> dict[str, Any]:
        """Advance to the next pending configuration action."""
        return self.env["res.config"]._next_todo_action()
