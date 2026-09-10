import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# base's own methods renamed for §2.4 (2026-09-10): the tail-marked domains
# take the free-standing form, a generate/apply/add that mutated takes the
# Mutation row, noun-first helpers gain their verb, and the commercial-sync
# family leads with the reserved verb. Rewritten wherever a stored block
# reaches the old name by attribute access, on 1.29's terms.
_RENAMES = (
    ("_get_eval_domain", "_get_domain_evaluated"),
    ("_get_action_domain", "_get_domain_for_action"),
    ("_get_inheriting_views_domain", "_get_domain_inheriting_views"),
    ("_get_name_search_domain", "_get_domain_name_search"),
    ("_generate_missing_avatars", "_update_missing_avatars"),
    ("_apply_group", "_add_implied_group"),
    ("_apply_textual_field_attrs", "_update_textual_field_attrs"),
    ("_add_html_header_footer", "_get_html_with_header_footer"),
    ("_add_company_resolution", "_get_company_resolution_info"),
    ("_load_menus_blacklist", "_get_blacklisted_menu_ids"),
    ("_esm_bridge_gc_grace_days", "_get_esm_bridge_gc_grace_days"),
    ("_esm_gc_grace_days", "_get_esm_gc_grace_days"),
    ("_esm_gc_collectable", "_get_esm_gc_collectable"),
    ("_fits_column", "_is_value_fitting_column"),
    ("_user_can_trust", "_can_user_trust"),
    ("_wants_multi_company_group", "_resolve_multi_company_group_membership"),
    ("_error_line_number", "_get_error_line_number"),
    ("_error_surrounding", "_get_error_surrounding_code"),
    ("_pg_sequence_name", "_get_pg_sequence_name"),
    ("_rate_history_scope", "_get_rate_history_scope"),
    ("__accessible_branches", "__get_accessible_branch_ids"),
    ("_children_sync", "_sync_children"),
    ("_commercial_sync_from_company", "_sync_commercial_fields_from_company"),
    ("_company_dependent_commercial_sync", "_sync_company_dependent_commercial_fields"),
    ("_commercial_sync_to_descendants", "_sync_commercial_fields_to_descendants"),
    ("_without_bin_size", "_with_bin_size_disabled"),
    ("_ranges_overlap", "_is_range_overlapping"),
    ("_covers", "_is_covering"),
    ("_installed", "_get_installed_module_ids"),
    ("_index", "_get_index_content"),
    ("_should_captcha_login", "_is_captcha_login_required"),
    ("_should_show_product", "_is_product_shown"),
    ("field_needs_variation", "is_field_variation_required"),
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
                    "base 1.44: %s.%s %s -> %s (%d row(s))",
                    table,
                    column,
                    old,
                    new,
                    cr.rowcount,
                )
