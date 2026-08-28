from odoo.db import schema

# The payment and its journal entry held each other: `account_payment.move_id`
# and `account_move.origin_payment_id`. `hr_expense` wrote both by hand, with a
# comment apologising for the recompute chain the second write set off.
#
# The edge is stored once now, on the payment. `origin_payment_id` keeps its name
# as the head of `account_move.payment_ids`, so every reader is unchanged, but it
# has no column and Odoo does not drop the column of a field that merely stopped
# being stored.
#
# The two columns were maintained by hand, so believe neither on its own:
# whichever side a row was linked from, the surviving column carries it.


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
