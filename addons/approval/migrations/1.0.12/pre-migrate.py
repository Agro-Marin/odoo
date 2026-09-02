import logging

_logger = logging.getLogger(__name__)

_MOVED_NAMES = (
    "model_approval_request_line",
    "field_approval_request__line_ids",
    "field_approval_request__has_product",
    "field_approval_category__has_product",
    "field_approval_category__product_ids",
    "approval_request_line_view_tree",
    "approval_request_line_view_tree_independent",
    "approval_product_kanban_mobile_view",
    "approval_request_line_view_form",
    "approvals_menu_product_template",
    "approvals_menu_product_variant",
    "access_approval_request_line",
    "approval_request_line_rule",
    "approval_request_line_user_read",
    "approval_request_line_restricted_users_read",
    "approval_request_line_restricted_groups_read",
    "approval_request_line_employees_read",
    "approval_request_line_user_write",
    "approval_request_line_manager_all",
)


def migrate(cr, version):
    cr.execute("SELECT 1 FROM ir_module_module WHERE name = 'approval_product'")
    if not cr.fetchone():
        _logger.warning(
            "19.0.1.0.12: approval_product not present; skipping ownership "
            "hand-over (product surface stays owned by approval)."
        )
        return

    cr.execute(
        """
        UPDATE ir_model_data d
        SET module = 'approval_product'
        WHERE d.module = 'approval'
          AND (d.name = ANY(%s) OR d.name LIKE 'field_approval_request_line__%%')
          AND NOT EXISTS (
              SELECT 1 FROM ir_model_data t
              WHERE t.module = 'approval_product' AND t.name = d.name
          )
        """,
        (list(_MOVED_NAMES),),
    )
    _logger.info(
        "19.0.1.0.12: handed %d record(s) over to approval_product.",
        cr.rowcount,
    )

    cr.execute(
        """
        DELETE FROM ir_model_data d
        WHERE d.module = 'approval'
          AND (d.name = ANY(%s) OR d.name LIKE 'field_approval_request_line__%%')
          AND EXISTS (
              SELECT 1 FROM ir_model_data t
              WHERE t.module = 'approval_product' AND t.name = d.name
          )
        """,
        (list(_MOVED_NAMES),),
    )
    if cr.rowcount:
        _logger.info(
            "19.0.1.0.12: dropped %d duplicate row(s) already owned by "
            "approval_product.",
            cr.rowcount,
        )
