import logging

from odoo.db import schema
from odoo.tools.module_data import rename_in_stored_expressions

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# Field hooks named for their field (§2.4.1), across the stock, sale, purchase,
# product and standalone families. A name only one model declares is rewritten
# wherever a stored block reaches it by attribute access, on 1.39's terms; a
# name several models declare -- `_compute_margin` is right on account.move and
# was wrong on sale.order -- is rewritten only for the model it was wrong on.
_RENAMES = (
    ("_get_plan_domain", "_get_domain_plan"),
    ("_get_rollup_lines_domain", "_get_domain_rollup_lines"),
    ("_get_transmission_domain", "_get_domain_transmission"),
    ("_get_active_products_domain", "_get_domain_active_products"),
    ("_base_domain_item_ids", "_get_domain_item_ids_base"),
    ("_get_applicable_rules_domain", "_get_domain_applicable_rules"),
    (
        "_get_partner_pricelist_multi_search_domain_hook",
        "_get_domain_partner_pricelist_multi_search",
    ),
    ("_get_product_count_domain", "_get_domain_product_count"),
    ("_get_valid_moves_domain", "_get_domain_valid_moves"),
    ("_rating_domain", "_get_domain_rating"),
    ("_get_program_domain", "_get_domain_program"),
    ("_get_trigger_domain", "_get_domain_trigger"),
    (
        "_get_additional_domain_for_purchase_order_line",
        "_get_domain_purchase_order_line_additional",
    ),
    ("_get_valuation_product_domain", "_get_domain_valuation_product"),
    ("_get_possible_pickings_domain", "_get_domain_possible_pickings"),
    ("_get_possible_batches_domain", "_get_domain_possible_batches"),
    ("_get_answer_matching_domain", "_get_domain_answer_matching"),
    ("_compute_auto_account", "_compute_auto_account_id"),
    ("_inverse_auto_account", "_inverse_auto_account_id"),
    ("_search_auto_account", "_search_auto_account_id"),
    ("_compute_delivery_state", "_compute_delivery_set"),
    ("_compute_is_service_products", "_compute_is_all_service"),
    ("_compute_mr_last_selected_id", "_compute_mondialrelay_last_selected_id"),
    ("_compute_mr_allowed_countries", "_compute_mondialrelay_allowed_countries"),
    ("_compute_clicks_count", "_compute_click_count"),
    ("_compute_count_active_cards", "_compute_loyalty_card_count"),
    ("_compute_partnership", "_compute_assigned_grade_id"),
    ("_compute_origin_po_count", "_compute_purchase_order_count"),
    ("_compute_suggested_quantity", "_compute_suggested_qty"),
    ("_search_product_with_suggested_quantity", "_search_suggested_qty"),
    ("_compute_rating_satisfaction", "_compute_rating_percentage_satisfaction"),
    ("_compute_product_is_in_repair", "_compute_product_catalog_product_is_in_repair"),
    ("_search_product_is_in_repair", "_search_product_catalog_product_is_in_repair"),
    ("_compute_last_reading", "_compute_last_reading_id"),
    ("_compute_reward_total", "_compute_reward_amount"),
    ("_compute_claimable_reward_ids", "_compute_reward_ids"),
    ("_compute_kpi_sale_total_value", "_compute_kpi_all_sale_total_value"),
    ("_search_is_valued", "_search_is_valued_internal"),
    ("_compute_invoice_ids", "_compute_invoices"),
    ("_compute_business_days", "_compute_day_counts"),
    ("_compute_count_transmission", "_compute_transmission_counts"),
    ("_compute_transmission_ids", "_compute_transmissions"),
    ("_compute_multi_product", "_compute_reward_products"),
    ("_compute_valid_product_ids", "_compute_valid_products"),
    ("_compute_receipt_reminder_email", "_compute_receipt_reminder"),
    ("_compute_rating_image", "_compute_rating_images"),
    ("_compute_parts_availability", "_compute_parts_availability_and_state"),
    ("_compute_unreserve_visible", "_compute_reservation_visibility"),
    ("_compute_sale_order_ids", "_compute_sale_orders"),
    ("_compute_value_justification", "_compute_value_justifications"),
    ("_compute_weight_is_kg", "_compute_weight_uom_info"),
    ("_compute_allowed_triggering_question_ids", "_compute_triggering_questions"),
    ("_compute_survey_url", "_compute_survey_urls"),
    ("_compute_answer_score", "_compute_answer_scoring"),
    ("_compute_count_transfer_incoming", "_compute_incoming_transfer_counts"),
    ("_compute_count_transfer_outgoing", "_compute_outgoing_transfer_counts"),
)

_RENAMES_BY_MODEL = (
    ("_product_id_domain", "_domain_product_id", "sale.order.template.line"),
    ("_compute_duration", "_compute_duration_days", "date.range"),
    ("_compute_owner", "_compute_owner_user_id", "maintenance.equipment"),
    ("_compute_owner", "_compute_owner_user_id", "maintenance.request"),
    ("_generate_code", "_prepare_code", "loyalty.card"),
    ("_compute_total_price", "_compute_price", "lunch.order"),
    ("_get_default_team_id", "_default_maintenance_team_id", "maintenance.request"),
    ("_compute_price_label", "_compute_price", "product.pricelist.item"),
    ("_compute_ordered_qty", "_compute_qty_ordered", "purchase.requisition.line"),
    ("_compute_total_amount", "_compute_amount_total", "stock.landed.cost"),
    (
        "_compute_maintenance_count",
        "_compute_maintenance_counts",
        "maintenance.equipment.category",
    ),
    (
        "_compute_maintenance_count",
        "_compute_maintenance_open_count",
        "mixin.maintenance",
    ),
    (
        "_compute_product_count",
        "_compute_product_counts",
        "update.product.attribute.value",
    ),
    (
        "_compute_authorized_transaction_ids",
        "_compute_authorized_transactions",
        "sale.order",
    ),
    ("_compute_sale_order_id", "_compute_sale_order", "hr.expense"),
    ("_compute_margin", "_compute_margins", "sale.order"),
    ("_compute_margin", "_compute_margins", "sale.order.line"),
    ("_compute_sale_order_count", "_compute_sale_orders", "purchase.order"),
    ("_compute_json_popover", "_compute_popover", "sale.order"),
    ("_compute_price", "_get_price", "product.pricelist.item"),
    (
        "_get_is_late_search_domain",
        "_get_domain_is_late_with_polarity",
        "purchase.order",
    ),
    ("_get_is_late_search_domain", "_get_domain_is_late_with_polarity", "mixin.order"),
)


def _pattern(name):
    return r"\." + name + r"\M"


def migrate(cr, version):
    if not version:
        return
    for table, column in _STORED_PYTHON:
        if not schema.table_exists(cr, table) or not schema.column_exists(
            cr, table, column
        ):
            continue
        for old, new in _RENAMES:
            cr.execute(
                f"UPDATE {table} SET {column} ="
                f" regexp_replace({column}, %(pat)s, %(new)s, 'g')"
                f" WHERE {column} ~ %(pat)s",
                {"pat": _pattern(old), "new": "." + new},
            )
            if cr.rowcount:
                _logger.info(
                    "base 1.43: %s.%s %s -> %s (%d row(s))",
                    table,
                    column,
                    old,
                    new,
                    cr.rowcount,
                )
    for old, new, model in _RENAMES_BY_MODEL:
        rename_in_stored_expressions(cr, old, new, model=model)
