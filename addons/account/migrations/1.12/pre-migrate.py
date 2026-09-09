from odoo.db import schema


def migrate(cr, version):
    if not version:
        return

    if not schema.column_exists(cr, "account_move", "origin_payment_id"):
        return

    cr.execute(
        """
        UPDATE account_payment p
           SET move_id = m.id
          FROM account_move m
         WHERE m.origin_payment_id = p.id
           AND p.move_id IS NULL
        """
    )

    cr.execute(
        """
        SELECT m.origin_payment_id, array_agg(m.id ORDER BY m.id)
          FROM account_move m
          JOIN account_payment p ON p.id = m.origin_payment_id
         WHERE p.move_id IS DISTINCT FROM m.id
         GROUP BY m.origin_payment_id
        """
    )
    if diverged := cr.fetchall():
        raise ValueError(
            "account_move.origin_payment_id and account_payment.move_id disagree "
            "for these payments, and only one of the two survives: "
            + "; ".join(f"payment {pid} <- moves {moves}" for pid, moves in diverged)
            + ". Reconcile them before upgrading."
        )

    cr.execute('ALTER TABLE "account_move" DROP COLUMN "origin_payment_id"')
