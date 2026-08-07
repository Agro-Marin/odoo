def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_ui_view
           SET arch_db = replace(
                   arch_db::text, 'installed_version', 'manifest_version'
               )::jsonb
         WHERE model = 'ir.module.module'
           AND arch_db::text LIKE '%installed_version%'
        """
    )
