from odoo.db.schema import table_exists

FROM_MODULE = "document_compliance"
TO_MODULE = "document"

KEPT_TYPE_FIELDS = (
    "is_mandatory",
    "is_renewable",
    "requires_original",
    "applies_to",
    "notification_days",
    "notification_partner_ids",
    "instructions",
)
DOCUMENT_FIELDS = (
    "document_type_id",
    "legal_number",
    "issuer_id",
    "date_issued",
    "date_expiration",
    "days_left",
    "expiration_state",
)
RECORDS = (
    "model_document_type",
    "constraint_document_type_code_company_uniq",
    "constraint_document_type_name_src_uniq",
    "constraint_document_document_legal_number_uniq",
    "view_document_type_search",
    "view_document_type_list",
    "view_document_type_form",
    "action_document_type",
    "menu_document_type",
)
RENAMED = {
    "ir_cron_find_and_set_documents_expired": "ir_cron_document_expiration_refresh",
}


def rehome_document_type(cr):
    if not table_exists(cr, "document_type"):
        return
    cr.execute(
        "SELECT id FROM ir_module_module "
        "WHERE name = %s AND state IN ('installed', 'to upgrade')",
        [FROM_MODULE],
    )
    if not cr.fetchone():
        return
    cr.execute(
        """
        UPDATE ir_model_data SET module = %(to)s
        WHERE module = %(from)s
          AND (name = ANY(%(records)s)
               OR name = ANY(%(document_fields)s)
               OR (name LIKE 'field_document_type\\_\\_%%'
                   AND name <> ALL(%(kept_type_fields)s)))
        """,
        {
            "to": TO_MODULE,
            "from": FROM_MODULE,
            "records": list(RECORDS),
            "document_fields": [
                f"field_document_document__{f}" for f in DOCUMENT_FIELDS
            ],
            "kept_type_fields": [f"field_document_type__{f}" for f in KEPT_TYPE_FIELDS],
        },
    )
    for old, new in RENAMED.items():
        cr.execute(
            "UPDATE ir_model_data SET module = %s, name = %s "
            "WHERE module = %s AND name = %s",
            [TO_MODULE, new, FROM_MODULE, old],
        )
    cr.execute(
        """
        UPDATE ir_act_server a SET code = 'model._cron_refresh_expiration_state()'
        FROM ir_cron c, ir_model_data d
        WHERE a.id = c.ir_actions_server_id
          AND d.model = 'ir.cron' AND d.res_id = c.id
          AND d.module = %s AND d.name = %s
        """,
        [TO_MODULE, RENAMED["ir_cron_find_and_set_documents_expired"]],
    )
    cr.execute(
        """
        UPDATE ir_model_constraint c SET module = t.id
        FROM ir_module_module t, ir_module_module f
        WHERE t.name = %s AND f.name = %s AND c.module = f.id
          AND c.name IN ('document_type_code_company_uniq',
                         'document_type_name_src_uniq',
                         'document_document_legal_number_uniq')
        """,
        [TO_MODULE, FROM_MODULE],
    )
    cr.execute(
        """
        UPDATE ir_model_relation r SET module = t.id
        FROM ir_module_module t, ir_module_module f
        WHERE t.name = %s AND f.name = %s AND r.module = f.id
          AND r.name = 'document_type_tag_rel'
        """,
        [TO_MODULE, FROM_MODULE],
    )


def migrate(cr, version):
    if not version:
        return
    rehome_document_type(cr)
