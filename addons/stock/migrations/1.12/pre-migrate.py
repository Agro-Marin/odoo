r"""Pre-migration: stock 1.12's field-hook renames, in stored Python.

ADR-0056: a method name written into ``ir_act_server.code`` is a binding no
checkout holds, and a leading underscore is not evidence a name is unreachable
-- the field is edited in the web client, so what ships is not what exists.
These fourteen are the renames §2.4 asked for on stock's field hooks.

Three of the seventeen are deliberately absent, because their OLD name is still
a live method on another model and a stored body naming one is not necessarily
naming stock's:

    _compute_location_id   still serves one field each on stock.move,
                           stock.picking, stock.lot, stock.scrap,
                           stock.warehouse.orderpoint and mrp's and repair's
                           overrides -- only stock.move.line's served two
    _compute_move_count    agromarin's documents.document
    _product_domain        website, website.sale and enterprise's renting

Every statement is idempotent: the guard stops matching once a row is rewritten.
"""

import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

RENAMES = (
    ("_compute_count_reordering_rules", "_compute_reordering_rules"),
    ("_compute_lead_days", "_compute_lead_time"),
    ("_compute_products_availability", "_compute_availability_status"),
    ("_compute_date_last_movement", "_compute_last_movement"),
    ("_compute_is_partial_package", "_compute_partial_packages"),
    ("_default_lot_sequence", "_default_lot_sequence_id"),
    ("_has_product_selectable_route", "_default_has_available_route_ids"),
    ("_inverse_inventory_quantity", "_inverse_inventory_quantity_auto_apply"),
    ("_compute_action_message", "_compute_rule_message"),
    ("_quantity_search_domain", "_get_domain_quantity_search"),
    ("_get_accessible_location_domain", "_get_domain_accessible_location"),
    ("_get_allocatable_demand_domain", "_get_domain_allocatable_demand"),
    ("_get_resupply_pick_leg_domain", "_get_domain_resupply_pick_leg"),
    ("_get_extra_domain", "_get_domain_extra"),
)

# ir_act_server.code is what a cron and a user-written server action run;
# ir_actions_server_history.code is the undo buffer a user can restore from,
# and an entry left unrewritten is a body that fails on restore.
# ir_model_fields.compute is NOT here: it holds a field's Python body, not a
# method name.
CODE_COLUMNS = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
)


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return
    for table, column in CODE_COLUMNS:
        if not _table_exists(cr, table):
            continue
        for old, new in RENAMES:
            _rewrite(cr, table, column, old, new)


def _table_exists(cr: "Cursor", table: str) -> bool:
    cr.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
    return bool(cr.fetchone()[0])


def _rewrite(cr: "Cursor", table: str, column: str, old: str, new: str) -> None:
    # \m and \M are Postgres word boundaries, and _ is a word character there:
    # _default_lot_sequence must not match inside _default_lot_sequence_id, nor
    # _compute_lead_days inside another module's _compute_lead_days_total.
    pattern = rf"\m{old}\M"
    cr.execute(
        f"UPDATE {table} SET {column} = regexp_replace({column}, %s, %s, 'g')"
        f" WHERE {column} ~ %s",
        (pattern, new, pattern),
    )
    if cr.rowcount:
        _logger.info(
            "stock 1.12: %s.%s %s -> %s (%d row(s))",
            table,
            column,
            old,
            new,
            cr.rowcount,
        )
