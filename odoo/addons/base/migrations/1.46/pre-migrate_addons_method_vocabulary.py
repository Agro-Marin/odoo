import logging

from odoo.db import schema
from odoo.tools.module_data import rename_in_stored_expressions

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# The 66 names under addons/ the widened naming gate of base 1.44 made visible
# (§2.4.8 modals, §2.4.12 generate-without-a-product, §2.4.22 one shaping
# call), renamed together; a name only one model declares is rewritten wherever
# a stored block reaches it by attribute access, on 1.29's terms, and the three
# that several models spell are rewritten per model.
_RENAMES = (
    ("_generate_deferred_entries", "_create_deferred_entries"),
    ("_generate_journal_entry", "_create_journal_entry"),
    ("_generate_common_warnings", "_add_common_warnings"),
    ("_generate_carryover_external_values", "_create_carryover_external_values"),
    ("_generate_default_external_values", "_create_default_external_values"),
    ("_generate_or_refresh_all_returns", "_sync_all_returns"),
    ("_generate_tax_closing_entries", "_create_tax_closing_entries"),
    ("_generate_dynamic_reports_for_move", "_create_dynamic_reports_for_move"),
    ("_generate_invoice_documents", "_render_invoice_documents"),
    ("_generate_invoice_fallback_documents", "_create_invoice_fallback_documents"),
    ("_generate_sinvoice_file_date", "_update_invoice_data_sinvoice_file"),
    ("_generate_timesheets", "_create_timesheets"),
    ("_generate_onboarding_todo", "_create_onboarding_todo"),
    ("generate_views", "update_action_views"),
    ("_generate_primary_snippet_templates", "_create_primary_snippet_templates"),
    ("_generate_primary_page_templates", "_create_primary_page_templates"),
    ("_should_use_bank_journal_export", "_is_bank_journal_export_required"),
    ("_need_cancel_request", "_is_cancel_request_required"),
    ("_should_detach_attachments", "_is_attachment_detach_required"),
    ("_must_check_constrains_date_sequence", "_is_date_sequence_check_required"),
    ("should_print_option", "is_option_printable"),
    ("needs_to_be_at_bottom", "is_bottom_placement_required"),
    ("_should_run_checks", "_is_check_run_required"),
    ("_should_attach_to_record", "_is_record_attachment_required"),
    ("_needs_web_services", "_is_web_service_required"),
    ("_need_ubl_cii_xml", "_is_ubl_cii_xml_required"),
    ("should_invalidate", "is_invalidation_required"),
    ("_must_check_identity", "_is_identity_check_required"),
    ("_should_be_locked", "_is_lock_required"),
    ("_should_update_price", "_is_price_update_required"),
    ("_should_update_discount", "_is_discount_update_required"),
    ("should_send_ping_frame", "is_ping_frame_required"),
    ("_should_notify_attendee", "_is_attendee_notification_required"),
    ("_need_video_call", "_is_video_call_required"),
    ("_needs_product_price_computation", "_is_product_price_computation_required"),
    ("_should_poll_to_connect_database", "_is_database_connect_poll_required"),
    (
        "_need_update_withholding_lines_placeholder",
        "_is_withholding_lines_placeholder_update_required",
    ),
    ("_should_invite_members_to_join_call", "_is_call_invitation_required"),
    ("_wants_unfollow_link", "_is_unfollow_link_required"),
    ("_must_render_template_value", "_is_template_value_render_required"),
    ("_need_new_activity", "_is_new_activity_required"),
    ("_should_build_inline_form", "_is_inline_form_required"),
    ("_needs_address", "_is_address_required"),
    ("_should_set_dest_address", "_is_dest_address_required"),
    ("_should_be_valued", "_is_valuation_required"),
    ("_should_create_account_move", "_is_account_move_required"),
    ("_should_exclude_for_valuation", "_is_excluded_from_valuation"),
    ("_should_include_inventory_loss", "_is_inventory_loss_included"),
    ("_should_generate_commercial_invoice", "_is_commercial_invoice_required"),
    ("_needs_customer_address", "_is_customer_address_required"),
    ("_should_show_strikethrough_price", "_is_strikethrough_price_shown"),
    ("_get_moves_requiring_confirmation", "_filtered_requiring_confirmation"),
    ("_get_discount_lines", "_filtered_discount_lines"),
    ("_check_line_unlink", "_filtered_unlink_forbidden"),
    ("_get_invalid_delivery_weight_lines", "_filtered_invalid_delivery_weight"),
    ("_get_leaves_on_public_holiday", "_filtered_on_public_holiday"),
    ("_get_leaves_entries_outside_schedule", "_filtered_leaves_outside_schedule"),
    ("_get_synced_events", "_filtered_synced"),
    ("_get_partner_pricelist_multi_filter_hook", "_filtered_partner_pricelist_multi"),
    ("_get_filtered_supplier", "_filtered_for_company_and_product"),
    ("_get_so_lines_task_global_project", "_filtered_task_global_project"),
    ("_get_so_lines_new_project", "_filtered_new_project"),
)

_RENAMES_BY_MODEL = (
    (
        "_generate_xml",
        "_create_efaktur_xml_attachment",
        "l10n_id_efaktur_coretax.document",
    ),
    ("_generate_xml", "_create_tbai_xml_attachment", "l10n_es_edi_tbai.document"),
    ("should_retry", "is_retry_required", "exchange.channel"),
    ("should_retry", "is_retry_required", "mixin.api.channel"),
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
                    "base 1.46: %s.%s %s -> %s (%d row(s))",
                    table,
                    column,
                    old,
                    new,
                    cr.rowcount,
                )
    for old, new, model in _RENAMES_BY_MODEL:
        rename_in_stored_expressions(cr, old, new, model=model)
