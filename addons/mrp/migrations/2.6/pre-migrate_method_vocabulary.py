import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# §2.4 renames on mrp's models, 2026-09-09. Every one is a method, so stored
# Python reaches it by attribute access from `env`, `record` or `model`, which
# is why each pattern is anchored on a leading dot: a bare spelling is the
# author's own local and is left alone. Overrides in mrp_account, sale_mrp,
# mrp_subcontracting and mrp_workorder wear the same names, so one row per
# name covers every module that declares it.
_RENAMES = (
    ("_get_mo_count", "_compute_mo_counts"),
    ("_check_planned_start", "_update_receipt_decorator"),
    ("_need_special_rules", "_has_special_rules"),
    ("_find_special_rules", "_get_special_rules"),
    ("_sum_costs", "_get_cost_sum"),
    ("_open_timer_groupby", "_get_open_timer_groupby"),
    ("_need_quantity_propagation", "_is_quantity_propagation_required"),
    ("_should_auto_confirm_procurement_mo", "_is_mo_auto_confirm_required"),
    ("_should_start_timer", "_is_timer_start_required"),
    ("_should_estimate_cost", "_is_cost_estimate_required"),
    ("_should_postpone_date_end", "_is_date_end_postponement_required"),
    ("_should_return_records", "_is_result_return_required"),
    ("_should_bypass_set_qty_producing", "_is_qty_producing_bypass_required"),
    ("_can_produce_serial_numbers", "_get_serial_numbers_warning"),
    ("_cal_price", "_update_finished_moves_price_unit"),
    ("_autoconfirm_production", "_confirm_draft_moves_and_workorders"),
    ("_autoprint_generated_lot", "_prepare_action_autoprint_generated_lot"),
    ("_autoprint_mass_generated_lots", "_prepare_actions_autoprint_generated_lots"),
    ("_autoprint_labels_by_format", "_add_actions_autoprint_by_format"),
    ("_get_autoprint_done_report_actions", "_prepare_actions_autoprint_done"),
    ("_generate_consume_moves", "_create_consume_moves"),
    ("_generate_produce_moves", "_create_produce_moves"),
    ("_generate_move_from_existing_move", "_create_move_from_existing_move"),
    ("_generate_move_from_bom_line", "_create_move_from_bom_line"),
    ("_get_backorder_mo_vals", "_prepare_backorder_mo_vals"),
    ("_get_backorder_move_vals", "_prepare_backorder_move_vals"),
    ("_get_move_finished_values", "_prepare_move_finished_vals"),
    ("_get_moves_finished_values", "_prepare_moves_finished_vals"),
    ("_get_move_raw_values", "_prepare_move_raw_vals"),
    ("_get_moves_raw_values", "_prepare_moves_raw_vals"),
    ("_get_operation_values", "_prepare_operation_vals"),
    ("_get_bom_values", "_prepare_bom_commands"),
    ("_get_new_catalog_line_values", "_prepare_new_catalog_line_vals"),
    ("_get_line_vals", "_prepare_wip_line_vals"),
    ("_prepare_mo_search_domain", "_get_domain_mo_for_procurement"),
    ("_should_postpone_date_finished", "_is_date_end_postponement_required"),
    ("_unlink_if_not_done", "_unlink_except_done_at_uninstall"),
)


def _pattern(name):
    return r"\." + name + r"\M"


def _rewrite(cr, table, column):
    moved = {}
    for old, new in _RENAMES:
        cr.execute(
            f"UPDATE {table} SET {column} ="
            f" regexp_replace({column}, %(pat)s, %(new)s, 'g')"
            f" WHERE {column} ~ %(pat)s",
            {"pat": _pattern(old), "new": "." + new},
        )
        if cr.rowcount:
            moved[old] = cr.rowcount
    return moved


def migrate(cr, version):
    if not version:
        return
    for table, column in _STORED_PYTHON:
        if not schema.table_exists(cr, table):
            continue
        if not schema.column_exists(cr, table, column):
            continue
        moved = _rewrite(cr, table, column)
        if moved:
            _logger.info(
                "mrp 2.6: rewrote %d method name(s) in %s.%s -- %s",
                len(moved),
                table,
                column,
                ", ".join(f"{name} x{count}" for name, count in sorted(moved.items())),
            )
