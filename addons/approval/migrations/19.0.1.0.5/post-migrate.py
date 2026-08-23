def migrate(cr, version):
    for old in (
        "approval_category_purchase_product_rel",
        "approval_category_sale_product_rel",
    ):
        cr.execute("SELECT to_regclass(%s)", (old,))
        if not cr.fetchone()[0]:
            continue
        cr.execute(f"""
            INSERT INTO approval_category_product_rel (category_id, product_id)
            SELECT category_id, product_id FROM {old} src
            WHERE NOT EXISTS (
                SELECT 1 FROM approval_category_product_rel r
                WHERE r.category_id = src.category_id
                  AND r.product_id = src.product_id
            )
        """)
        cr.execute(f"DROP TABLE IF EXISTS {old}")
