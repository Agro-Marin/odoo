OLD = "account_payment"
NEW = "account_payment_provider"

OLD_PARAM = f"{OLD}.enable_portal_payment"
NEW_PARAM = f"{NEW}.enable_portal_payment"

# ADR-0070: the module bridges accounting to the payment engine and defines no
# `account.payment` -- that model lives here, in `account`.
#
# The rename lives in `account` and not in the renamed module's own
# `pre_init_hook`, which is where `credential` put the same job, because that
# hook cannot fire: the renamed module is `auto_install`, and Odoo will not
# auto-install it while a row named `account_payment` sits in `ir_module_module`
# with no directory behind it -- it reports `manifest not found`, skips the
# module, and ends the upgrade with "Some modules have inconsistent states".
# Measured, not assumed. `account` is the only module guaranteed both to be
# upgraded and to load before the renamed one.
#
# **Nothing here deletes an `ir_module_module` row.** `update_list` has already
# created one for the new module by the time this runs, and the registry holds
# it: deleting it crashes the same upgrade later, in `_compute_description_html`,
# with `Record does not exist or has been deleted` -- measured under `-u all`,
# which is the shape a real upgrade takes. The new row is given the old one's
# state instead, and the old one is retired the way `credential` retired its
# predecessor.


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
        # No row for the new module yet -- rename rather than create, so the
        # history and the id stay with the module.
        cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (NEW, OLD))

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (NEW, OLD))
    cr.execute(
        "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s", (NEW, OLD)
    )

    # A QWeb view's `key` is namespaced by its module and is what an unprefixed
    # `t-call` resolves against, so leaving it behind fails the upgrade with
    # `The ID "account_payment.portal_docs_entry" refers to an uninstalled
    # module` -- measured, and the last thing this rename needed.
    cr.execute(
        "UPDATE ir_ui_view SET key = %s || substring(key from %s) WHERE key LIKE %s",
        (f"{NEW}.", len(OLD) + 2, f"{OLD}.%"),
    )

    # `noupdate="1" forcecreate="0"`, so a data reload never rewrites this key.
    cr.execute(
        "UPDATE ir_config_parameter SET key = %s WHERE key = %s "
        "AND NOT EXISTS (SELECT 1 FROM ir_config_parameter WHERE key = %s)",
        (NEW_PARAM, OLD_PARAM, NEW_PARAM),
    )

    # Retired, not removed: the directory is gone, so Odoo will log
    # `manifest not found` and skip it, which is what `credential` left behind
    # too. Removing it is what the comment above says not to do.
    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s AND id <> "
        "COALESCE((SELECT id FROM ir_module_module WHERE name = %s), -1)",
        (OLD, NEW),
    )
