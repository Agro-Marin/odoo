UNITS = (("days", "day"), ("weeks", "week"), ("months", "month"))

FIELDS = (
    ("mail.activity.type", "delay_unit"),
    ("mail.activity.plan.template", "delay_unit"),
    ("ir.actions.server", "activity_date_deadline_range_type"),
)


def migrate(cr, version):
    if not version:
        return

    for old, new in UNITS:
        cr.execute(
            "UPDATE mail_activity_type SET delay_unit = %s WHERE delay_unit = %s",
            (new, old),
        )
        cr.execute(
            "UPDATE mail_activity_plan_template SET delay_unit = %s"
            " WHERE delay_unit = %s",
            (new, old),
        )
        cr.execute(
            "UPDATE ir_act_server SET activity_date_deadline_range_type = %s"
            " WHERE activity_date_deadline_range_type = %s",
            (new, old),
        )

    for model, field in FIELDS:
        for old, new in UNITS:
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
                (f'"{new}"', model, field, f'"{old}"'),
            )
