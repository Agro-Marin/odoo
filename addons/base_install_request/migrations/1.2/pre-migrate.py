def migrate(cr, version):
    """Hand the approval half to its bridge on databases that already took it.

    1.1 made this module depend on `approval`. It is auto-installed on every
    database, so that was a dependency of every database, and one that never had
    `approval` skipped the module on its next start instead of upgrading into
    it. 1.2 depends on `mail` again and `approval_base_install_request` carries
    the approval request. A database that did upgrade to 1.1 has `approval`, a
    request table carrying approval columns and the activation category: it gets
    the bridge in this same load, and the category's external ids move to it so
    the bridge updates the records rather than creating second copies.
    """
    cr.execute("SELECT state FROM ir_module_module WHERE name = 'approval'")
    row = cr.fetchone()
    if not row or row[0] not in ("installed", "to upgrade", "to install"):
        return
    cr.execute(
        """
        UPDATE ir_model_data
           SET module = 'approval_base_install_request'
         WHERE module = 'base_install_request'
           AND name = ANY(%s)
        """,
        [
            [
                "approval_category_module_activation",
                "approval_category_step_module_activation",
            ]
        ],
    )
    cr.execute(
        """
        UPDATE ir_module_module
           SET state = 'to install'
         WHERE name = 'approval_base_install_request'
           AND state = 'uninstalled'
        """
    )
