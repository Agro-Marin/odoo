def migrate(cr, version):
    cr.execute(r"""
        UPDATE ir_ui_view
        SET arch_db = REGEXP_REPLACE(arch_db::text, '<div[^<]*>[^<]*<input[^>]+id=\\"csrf_token\\"[^>]*/>[^<]*</div>', '', 'g')::jsonb
        WHERE key = 'website_hr_recruitment.apply'
        AND website_id IS NOT NULL
        AND arch_db::text LIKE '%csrf_token%'
    """)
