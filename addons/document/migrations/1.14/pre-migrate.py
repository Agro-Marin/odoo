UNITS = (("days", "day"), ("weeks", "week"), ("months", "month"))

MODEL = "document.document"
FIELD = "create_activity_date_deadline_range_type"


def migrate(cr, version):
    if not version:
        return

    for old, new in UNITS:
        cr.execute(
            "UPDATE document_document"
            " SET create_activity_date_deadline_range_type = %s"
            " WHERE create_activity_date_deadline_range_type = %s",
            (new, old),
        )
        cr.execute(
            """
            UPDATE ir_default d
               SET json_value = %s
              FROM ir_model_fields f
             WHERE f.id = d.field_id
               AND f.model = %s
               AND f.name = %s
               AND d.json_value = %s
            """,
            (f'"{new}"', MODEL, FIELD, f'"{old}"'),
        )
