import logging

from odoo.db.schema import column_exists, table_exists
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

REL = "res_partner_res_partner_bank_rel"


def _drop_stale_unique_constraints(cr):
    """Drop whichever spelling of the account-number unique this tree carried.

    1.36 shipped ``unique(sanitized_acc_number)`` and the release before it
    ``unique(sanitized_acc_number, partner_id)``. Both reject rows this script
    has to write, and the ORM installs the new one after it runs, so neither is
    matched by name -- the column set is what identifies them.
    """
    cr.execute(
        """
        SELECT c.conname
          FROM pg_constraint c
          JOIN pg_class t ON t.oid = c.conrelid
         WHERE c.contype = 'u' AND t.relname = 'res_partner_bank'
           AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
                  FROM pg_attribute a
                 WHERE a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
               ) && ARRAY['sanitized_acc_number']
        """
    )
    for (conname,) in cr.fetchall():
        cr.execute(f'ALTER TABLE res_partner_bank DROP CONSTRAINT "{conname}"')


def _repoint_one_column(cr, table, column, survivor, duplicates):
    # On a relation table the column is half of the primary key, so a row
    # whose other half already points at the survivor would collide once it
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


def _repoint_foreign_keys(cr, survivor, duplicates):
    """Move everything that names a folded-away account onto the survivor."""
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
        _repoint_one_column(cr, table, column, survivor, duplicates)
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


def _restore_the_holder_column(cr):
    """Undo 1.36: partner_id from the relation, a row per holder that fits."""
    if not column_exists(cr, "res_partner_bank", "partner_id"):
        cr.execute("ALTER TABLE res_partner_bank ADD COLUMN partner_id integer")

    cr.execute(
        f"""
        UPDATE res_partner_bank account
           SET partner_id = holder.partner_id
          FROM (SELECT bank_account_id, min(partner_id) AS partner_id
                  FROM {REL} GROUP BY bank_account_id) holder
         WHERE holder.bank_account_id = account.id
           AND account.partner_id IS NULL
        """
    )

    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_schema = current_schema() AND table_name = 'res_partner_bank'
           AND column_name NOT IN ('id', 'partner_id', 'company_id')
        """
    )
    columns = [name for (name,) in cr.fetchall()]
    copied = ", ".join(f'"{name}"' for name in columns)
    selected = ", ".join(
        "false" if name == "allow_out_payment" else f'account."{name}"'
        for name in columns
    )
    # A holder belonging to no company always gets its row, since the
    # constraint does not compare nulls. A holder that brings a company gets
    # one only if that company does not already hold the number, which the
    # survivor's company does; DISTINCT ON keeps the first of any tie.
    cr.execute(
        f"""
        INSERT INTO res_partner_bank (partner_id, company_id, {copied})
        SELECT DISTINCT ON (
                   account.sanitized_acc_number,
                   coalesce(holder.company_id, -rel.partner_id)
               )
               rel.partner_id, holder.company_id, {selected}
          FROM res_partner_bank account
          JOIN {REL} rel ON rel.bank_account_id = account.id
          JOIN res_partner holder ON holder.id = rel.partner_id
          JOIN res_partner kept ON kept.id = account.partner_id
         WHERE rel.partner_id <> account.partner_id
           AND (holder.company_id IS NULL
                OR holder.company_id IS DISTINCT FROM kept.company_id)
         ORDER BY account.sanitized_acc_number,
                  coalesce(holder.company_id, -rel.partner_id),
                  rel.partner_id
        """
    )
    split = cr.rowcount

    cr.execute(
        f"""
        SELECT count(*) FROM {REL} rel
          JOIN res_partner_bank account ON account.id = rel.bank_account_id
         WHERE rel.partner_id <> account.partner_id
        """
    )
    (co_held,) = cr.fetchone()
    cr.execute(f"DROP TABLE {REL}")
    return split, co_held - split


def _fold_rows_the_new_constraint_forbids(cr):
    """One row per (number, company), for the rows that name a company.

    GROUP BY puts every null company in one bucket where the constraint leaves
    them apart, so the rows without a company are excluded rather than folded:
    two shared contacts holding one number stays a state this release allows,
    and the merge wizard is what resolves it.
    """
    cr.execute(
        """
        SELECT min(id), array_agg(id ORDER BY id)
          FROM res_partner_bank
         WHERE sanitized_acc_number IS NOT NULL AND company_id IS NOT NULL
         GROUP BY sanitized_acc_number, company_id
        HAVING count(*) > 1
        """
    )
    folded = 0
    for survivor, ids in cr.fetchall():
        duplicates = [i for i in ids if i != survivor]
        _repoint_foreign_keys(cr, survivor, duplicates)
        cr.execute("DELETE FROM res_partner_bank WHERE id = ANY(%s)", (duplicates,))
        folded += len(duplicates)
    return folded


def migrate(cr, version):
    if not version:
        return
    _drop_stale_unique_constraints(cr)

    split = dropped = 0
    if table_exists(cr, REL):
        split, dropped = _restore_the_holder_column(cr)

    cr.execute(
        """
        UPDATE res_partner_bank account
           SET company_id = partner.company_id
          FROM res_partner partner
         WHERE partner.id = account.partner_id
        """
    )

    folded = _fold_rows_the_new_constraint_forbids(cr)

    cr.execute("SELECT count(*) FROM res_partner_bank WHERE partner_id IS NULL")
    (orphans,) = cr.fetchone()
    if orphans:
        _logger.warning(
            "bank holders: %s accounts name no holder at all and keep a null "
            "partner_id; the field is required, so each needs one assigned by "
            "hand before that row can be written again",
            orphans,
        )
    if dropped:
        _logger.warning(
            "bank holders: %s co-holders were not given a row of their own, "
            "because their company already records that account number; the "
            "account stays under its lowest-numbered holder",
            dropped,
        )
    if folded:
        _logger.warning(
            "bank holders: %s rows repeated an account number inside one "
            "company and were folded into the lowest-numbered one, which every "
            "reference to them now names",
            folded,
        )
    _logger.info(
        "bank holders: partner_id restored, %s accounts split out for a holder "
        "in another company, each untrusted until it is verified again",
        split,
    )
