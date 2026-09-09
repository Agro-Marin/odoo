RENAMED_VIEWS = [
    "res_config_settings_view_form",
    "setup_financial_year_opening_form",
    "view_account_form",
    "view_company_form",
]


def migrate(cr, version):
    if not version:
        return

    # account_reports 1.1 suffixed these four to clear a collision with account's own
    # ids. A database that never ran that migration upgrades straight into the fold, so
    # apply it here too; it is a no-op where 1.1 already ran.
    cr.execute(
        """
        UPDATE ir_model_data
           SET name = name || '_reports'
         WHERE module = 'account_reports'
           AND model = 'ir.ui.view'
           AND name = ANY(%s)
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_data d
                WHERE d.module = 'account_reports'
                  AND d.name = ir_model_data.name || '_reports'
           )
        """,
        [RENAMED_VIEWS],
    )

    # Stop before writing if anything would collide, rather than after. ir_model_data is
    # UNIQUE (module, name), so a name account already owns would abort the whole upgrade
    # with a constraint error naming no ids; this names them.
    cr.execute(
        """
        SELECT r.model, r.name
          FROM ir_model_data r
          JOIN ir_model_data a ON a.module = 'account' AND a.name = r.name
         WHERE r.module = 'account_reports'
        """
    )
    if collisions := cr.fetchall():
        raise ValueError(
            "account_reports cannot fold into account: %s xmlid(s) exist in both, "
            "rename them before upgrading -- %s"
            % (len(collisions), ", ".join(f"{m}:{n}" for m, n in collisions[:20]))
        )

    # Repoint, never delete. An xmlid whose module no longer declares it is reaped and the
    # record behind it destroyed; ir_ui_view_custom.ref_id alone is CASCADE, so that would
    # silently delete every user's view customisation. Moving the row keeps every record id.
    cr.execute(
        "UPDATE ir_model_data SET module = 'account' WHERE module = 'account_reports'"
    )

    # The module is absorbed, not renamed, so its own row and the dependency edges naming
    # it are now phantoms -- the 120 dependents' manifests name `account` instead. Left in
    # place they keep the module reading `installed` with nothing on disk behind it.
    # Two transient models carried the old module in their _name. Renamed with the fold,
    # so ir_model, its xmlid and the backing table have to follow; nothing is stored in a
    # TransientModel long enough to migrate, but the rows and the table are real.
    for old, new in (
        ("account_reports.export.wizard", "account.export.wizard"),
        ("account_reports.export.wizard.format", "account.export.wizard.format"),
    ):
        cr.execute("UPDATE ir_model SET model = %s WHERE model = %s", (new, old))
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE model = 'ir.model' AND name = %s",
            ("model_" + new.replace(".", "_"), "model_" + old.replace(".", "_")),
        )
        cr.execute("UPDATE ir_model_fields SET model = %s WHERE model = %s", (new, old))
        cr.execute(
            "ALTER TABLE IF EXISTS %s RENAME TO %s"
            % (old.replace(".", "_"), new.replace(".", "_"))
        )

    cr.execute("DELETE FROM ir_module_module_dependency WHERE name = 'account_reports'")
    cr.execute("DELETE FROM ir_module_module WHERE name = 'account_reports'")
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'base' AND name = 'module_account_reports'"
    )
