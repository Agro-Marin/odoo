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
        # On a relation table the column is half of the primary key, so a row
        # whose partner already points at the survivor would collide once it
        # is repointed. Drop those first; the survivor already carries them.
        cr.execute(
            """
            SELECT a.attname
              FROM pg_index i
              JOIN pg_attribute a ON a.attrelid = i.indrelid
                                 AND a.attnum = ANY(i.indkey)
             WHERE i.indrelid = %s::regclass AND i.indisprimary
            """,
            (table,),
        )
        key = [name for (name,) in cr.fetchall() if name != column]
        if key:
            match = SQL(" AND ").join(
                SQL("keep.%(k)s = dup.%(k)s", k=SQL.identifier(name)) for name in key
            )
            cr.execute(
                SQL(
                    "DELETE FROM %(t)s dup"
                    " WHERE dup.%(c)s = ANY(%(d)s)"
                    " AND EXISTS (SELECT 1 FROM %(t)s keep"
                    " WHERE keep.%(c)s = %(s)s AND %(match)s)",
                    t=SQL.identifier(table),
                    c=SQL.identifier(column),
                    s=survivor,
                    d=duplicates,
                    match=match,
                )
            )
        cr.execute(
            SQL(
                "UPDATE %(t)s SET %(c)s = %(s)s WHERE %(c)s = ANY(%(d)s)",
                t=SQL.identifier(table),
                c=SQL.identifier(column),
                s=survivor,
                d=duplicates,
            )
        )
    for table, model_column in (
        ("ir_attachment", "res_model"),
        ("ir_model_data", "model"),
        ("mail_message", "model"),
        ("mail_activity", "res_model"),
    ):
        cr.execute(
            SQL(
                "UPDATE %(t)s SET res_id = %(s)s"
                " WHERE %(m)s = 'res.partner.bank' AND res_id = ANY(%(d)s)",
                t=SQL.identifier(table),
                m=SQL.identifier(model_column),
                s=survivor,
                d=duplicates,
            )
        )
    # A follower is unique per (record, party), so the ones the survivor
    # already has are dropped rather than moved onto it.
    cr.execute(
        """
        DELETE FROM mail_followers dup
         WHERE dup.res_model = 'res.partner.bank' AND dup.res_id = ANY(%s)
           AND EXISTS (
               SELECT 1 FROM mail_followers keep
                WHERE keep.res_model = 'res.partner.bank'
                  AND keep.res_id = %s
                  AND keep.partner_id = dup.partner_id
           )
        """,
        (duplicates, survivor),
    )
    cr.execute(
        """
        UPDATE mail_followers SET res_id = %s
         WHERE res_model = 'res.partner.bank' AND res_id = ANY(%s)
        """,
        (survivor, duplicates),
    )


def migrate(cr, version):
    if not version:
        return
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
