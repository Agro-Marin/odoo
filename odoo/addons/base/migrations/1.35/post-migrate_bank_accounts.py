from odoo.db.schema import column_exists
from odoo.tools import SQL


def _repoint_foreign_keys(cr, survivor, duplicates):
    cr.execute(
        """
        SELECT c1.relname, a1.attname
          FROM pg_constraint fk
          JOIN pg_class c1 ON fk.conrelid = c1.oid
          JOIN pg_class c2 ON fk.confrelid = c2.oid
          JOIN pg_attribute a1 ON a1.attrelid = c1.oid AND fk.conkey[1] = a1.attnum
         WHERE fk.contype = 'f' AND c2.relname = 'res_partner_bank'
           AND c1.relnamespace = current_schema::regnamespace
        """
    )
    for table, column in cr.fetchall():
        cr.execute(
            SQL(
                "UPDATE %(t)s SET %(c)s = %(s)s WHERE %(c)s = ANY(%(d)s)",
                t=SQL.identifier(table),
                c=SQL.identifier(column),
                s=survivor,
                d=duplicates,
            )
        )
    cr.execute(
        """
        UPDATE ir_attachment SET res_id = %s
         WHERE res_model = 'res.partner.bank' AND res_id = ANY(%s)
        """,
        (survivor, duplicates),
    )


def migrate(env, version):
    cr = env.cr
    if not column_exists(cr, "res_partner_bank", "partner_id"):
        return
    cr.execute(
        """
        INSERT INTO res_partner_res_partner_bank_rel (partner_id, bank_account_id)
        SELECT partner_id, id FROM res_partner_bank WHERE partner_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    cr.execute(
        """
        SELECT min(id), array_agg(id ORDER BY id)
          FROM res_partner_bank
         WHERE sanitized_acc_number IS NOT NULL
         GROUP BY sanitized_acc_number
        HAVING count(*) > 1
        """
    )
    for survivor, ids in cr.fetchall():
        duplicates = [i for i in ids if i != survivor]
        cr.execute(
            """
            INSERT INTO res_partner_res_partner_bank_rel (partner_id, bank_account_id)
            SELECT partner_id, %s FROM res_partner_bank
             WHERE id = ANY(%s) AND partner_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """,
            (survivor, duplicates),
        )
        cr.execute(
            "DELETE FROM res_partner_res_partner_bank_rel WHERE bank_account_id = ANY(%s)",
            (duplicates,),
        )
        _repoint_foreign_keys(cr, survivor, duplicates)
        cr.execute("DELETE FROM res_partner_bank WHERE id = ANY(%s)", (duplicates,))
    cr.execute("ALTER TABLE res_partner_bank DROP COLUMN partner_id")
