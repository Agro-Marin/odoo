from odoo.db.schema import table_exists

FROM_MODULE = "document_compliance"
TO_MODULE = "document"

XMLIDS = (
    "field_document_type__is_renewable",
    "field_document_document__is_renewable",
    "field_document_document__renewal_document_id",
    "field_document_document__renewal_ids",
    "field_document_document__renewed_by_document_id",
    "field_document_document__renewal_count",
    "constraint_document_document_renewal_document_uniq",
)


def migrate(cr, version):
    if not version or not table_exists(cr, "document_type"):
        return
    cr.execute(
        "UPDATE ir_model_data SET module = %s WHERE module = %s AND name = ANY(%s)",
        [TO_MODULE, FROM_MODULE, list(XMLIDS)],
    )
    cr.execute(
        """
        UPDATE ir_model_constraint c SET module = t.id
        FROM ir_module_module t, ir_module_module f
        WHERE t.name = %s AND f.name = %s AND c.module = f.id
          AND c.name = 'document_document_renewal_document_uniq'
        """,
        [TO_MODULE, FROM_MODULE],
    )
