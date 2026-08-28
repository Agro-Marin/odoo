import re

from odoo.db import schema

OLD_MODEL = "account.payment.method.line"
NEW_MODEL = "account.payment.channel"
OLD_TABLE = "account_payment_method_line"
NEW_TABLE = "account_payment_channel"

# The negative lookahead is load-bearing, not decoration: `payment_method_linepay`
# is the LINE Pay provider method, a `payment.method` record whose xmlid carries
# the token and has nothing to do with this model.
RENAMED = "regexp_replace({}, 'payment_method_line(?!pay)', 'payment_channel', 'g')"

MATCHES = "{} ~ 'payment_method_line(?!pay)'"

# Columns this module owns. Every other module renames its own; the metadata
# below is rewritten here instead, unscoped, because `account` owns the model
# every one of those fields points at and loads before all of them -- four more
# scripts carrying this same regex would be four more places for it to drift.
OWN_COLUMNS = (
    ("account_payment", "payment_method_line_id", "payment_channel_id"),
    (
        "account_move",
        "preferred_payment_method_line_id",
        "preferred_payment_channel_id",
    ),
    ("account_payment_register", "payment_method_line_id", "payment_channel_id"),
    (
        "res_partner",
        "property_inbound_payment_method_line_id",
        "property_inbound_payment_channel_id",
    ),
    (
        "res_partner",
        "property_outbound_payment_method_line_id",
        "property_outbound_payment_channel_id",
    ),
)


def _renamed(name):
    return re.sub(r"payment_method_line(?!pay)", "payment_channel", name)


def migrate(cr, version):
    if not version:
        return

    if schema.table_exists(cr, OLD_TABLE) and not schema.table_exists(cr, NEW_TABLE):
        cr.execute(f'ALTER TABLE "{OLD_TABLE}" RENAME TO "{NEW_TABLE}"')
        # RENAME TO leaves an owned sequence under its old name.
        cr.execute(
            f'ALTER SEQUENCE IF EXISTS "{OLD_TABLE}_id_seq" RENAME TO "{NEW_TABLE}_id_seq"'
        )

    for table, old, new in OWN_COLUMNS:
        if schema.column_exists(cr, table, old) and not schema.column_exists(
            cr, table, new
        ):
            cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')

    # RENAME TO carries neither the constraints nor the indexes, so without this
    # the old spelling outlives the rename in every schema dump. Odoo matches a
    # foreign key on (table, column) and not on its name -- measured: the upgrade
    # adds no duplicate -- so this is legibility, not correctness, and
    # ir_model_constraint moves with it so the two keep agreeing.
    cr.execute(
        """
        SELECT c.conrelid::regclass::text, c.conname
          FROM pg_constraint c
         WHERE c.conrelid <> 0
           AND c.conname ~ 'payment_method_line(?!pay)'
        """
    )
    for table, name in cr.fetchall():
        cr.execute(
            f'ALTER TABLE {table} RENAME CONSTRAINT "{name}" TO "{_renamed(name)}"'
        )

    # A constraint-backed index followed its constraint; what is left is a plain
    # index and renames on its own.
    cr.execute(
        """
        SELECT indexname FROM pg_indexes
         WHERE schemaname = current_schema()
           AND indexname ~ 'payment_method_line(?!pay)'
        """
    )
    for (name,) in cr.fetchall():
        cr.execute(f'ALTER INDEX "{name}" RENAME TO "{_renamed(name)}"')

    cr.execute(
        f"UPDATE ir_model_constraint SET name = {RENAMED.format('name')} WHERE {MATCHES.format('name')}"
    )

    cr.execute(
        "UPDATE ir_model SET model = %s WHERE model = %s", (NEW_MODEL, OLD_MODEL)
    )
    cr.execute(
        "UPDATE ir_model_fields SET model = %s WHERE model = %s", (NEW_MODEL, OLD_MODEL)
    )
    cr.execute(
        "UPDATE ir_model_fields SET relation = %s WHERE relation = %s",
        (NEW_MODEL, OLD_MODEL),
    )
    cr.execute(
        "UPDATE ir_ui_view SET model = %s WHERE model = %s", (NEW_MODEL, OLD_MODEL)
    )

    cr.execute(
        f"UPDATE ir_model_fields SET name = {RENAMED.format('name')} WHERE {MATCHES.format('name')}"
    )
    cr.execute(
        f"""
        UPDATE ir_model_data
           SET name = {RENAMED.format("name")}
         WHERE {MATCHES.format("name")}
           AND model IN ('ir.model', 'ir.model.fields', 'ir.model.access', 'ir.ui.view')
        """
    )

    # A view, filter or action a user built by hand is the only one not reloaded
    # from XML by this upgrade, and the token names nothing else in any of them.
    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {RENAMED.format("arch_db::text")}::jsonb
         WHERE {MATCHES.format("arch_db::text")}
        """
    )
    cr.execute(
        f"""
        UPDATE ir_filters
           SET domain = {RENAMED.format("domain")},
               context = {RENAMED.format("context")},
               sort = {RENAMED.format("sort")}
         WHERE {MATCHES.format("domain")} OR {MATCHES.format("context")} OR {MATCHES.format("sort")}
        """
    )
    cr.execute(
        f"""
        UPDATE ir_act_window
           SET domain = {RENAMED.format("domain")},
               context = {RENAMED.format("context")}
         WHERE {MATCHES.format("domain")} OR {MATCHES.format("context")}
        """
    )
    cr.execute(
        f"""
        UPDATE ir_exports_line l
           SET name = {RENAMED.format("l.name")}
         WHERE {MATCHES.format("l.name")}
        """
    )
