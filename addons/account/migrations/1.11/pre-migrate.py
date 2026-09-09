OLD = "account_payment"
NEW = "account_payment_provider"

OLD_PARAM = f"{OLD}.enable_portal_payment"
NEW_PARAM = f"{NEW}.enable_portal_payment"


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        "SELECT id, state, db_version FROM ir_module_module WHERE name = %s", (OLD,)
    )
    old_row = cr.fetchone()
    if not old_row:
        return
    _old_id, old_state, old_db_version = old_row

    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (NEW,))
    if cr.fetchone():
        cr.execute(
            "UPDATE ir_module_module SET state = %s, db_version = %s WHERE name = %s",
            (old_state, old_db_version, NEW),
        )
    else:
        cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (NEW, OLD))

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (NEW, OLD))
    cr.execute(
        "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s", (NEW, OLD)
    )

    cr.execute(
        "UPDATE ir_ui_view SET key = %s || substring(key from %s) WHERE key LIKE %s",
        (f"{NEW}.", len(OLD) + 2, f"{OLD}.%"),
    )

    cr.execute(
        "UPDATE ir_config_parameter SET key = %s WHERE key = %s "
        "AND NOT EXISTS (SELECT 1 FROM ir_config_parameter WHERE key = %s)",
        (NEW_PARAM, OLD_PARAM, NEW_PARAM),
    )

    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s AND id <> "
        "COALESCE((SELECT id FROM ir_module_module WHERE name = %s), -1)",
        (OLD, NEW),
    )
