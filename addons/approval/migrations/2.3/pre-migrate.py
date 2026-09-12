from odoo import SUPERUSER_ID, api

from odoo.addons.approval_app import _adopt_engine_shell


def migrate(cr, version):
    """Hand the Approvals application shell to `approval_app`.

    2.3 ships no menu root, generic request categories or demo: those are
    `approval_app`. A database that had them keeps them, so the module is marked
    `to upgrade`, including when an upgrade of a module depending on it already
    marked it `to install`: an install loads data in init mode, which rewrites
    noupdate records, and would reset categories a company has since edited to
    their shipped values. The loader reads that state when the module's turn
    comes, after this script.
    """
    _adopt_engine_shell(cr)
    cr.execute("SELECT 1 FROM ir_module_module WHERE name = 'approval_app'")
    if not cr.fetchone():
        api.Environment(cr, SUPERUSER_ID, {})["ir.module.module"].update_list()
    cr.execute(
        """
        UPDATE ir_module_module AS app
           SET state = 'to upgrade',
               demo = engine.demo
          FROM ir_module_module AS engine
         WHERE app.name = 'approval_app'
           AND app.state IN ('uninstalled', 'to install')
           AND engine.name = 'approval'
        """
    )
