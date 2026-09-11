def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE ir_model_data AS source
           SET module = 'resource'
         WHERE source.module = 'planning'
           AND source.model = 'ir.model.fields'
           AND source.name = ANY(%s)
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_data AS target
                WHERE target.module = 'resource' AND target.name = source.name
           )
    """,
        [
            [
                "field_resource_resource__role_ids",
                "field_resource_resource__default_role_id",
                "field_resource_role__resource_ids",
            ]
        ],
    )
    cr.execute("""
        UPDATE ir_model_relation
           SET module = (SELECT id FROM ir_module_module WHERE name = 'resource')
         WHERE name = 'resource_resource_role_rel'
           AND module = (SELECT id FROM ir_module_module WHERE name = 'planning')
    """)
