from odoo.db import schema

# The settlement and its provider transaction used to hold each other:
# `account_payment.payment_transaction_id` and `payment_transaction.payment_id`,
# written eleven lines apart in `_create_payment` under a comment announcing a
# one2one. The edge is stored once now, on the payment, and a partial unique
# index makes that one2one real. This runs in `pre` and not in `post` because the
# index is built by `_auto_init`, which is between the two.


def migrate(cr, version):
    if not version:
        return

    if schema.column_exists(
        cr, "account_payment", "payment_transaction_id"
    ) and not schema.column_exists(cr, "account_payment", "transaction_id"):
        cr.execute(
            'ALTER TABLE "account_payment" RENAME COLUMN "payment_transaction_id" TO "transaction_id"'
        )
        cr.execute(
            "UPDATE ir_model_fields SET name = 'transaction_id' "
            "WHERE model = 'account.payment' AND name = 'payment_transaction_id'"
        )
        cr.execute(
            "UPDATE ir_model_data SET name = 'field_account_payment__transaction_id' "
            "WHERE model = 'ir.model.fields' AND name = 'field_account_payment__payment_transaction_id'"
        )

    # The two columns were maintained by hand, so believe neither on its own:
    # whichever side a row was linked from, the surviving column carries it.
    if schema.column_exists(cr, "payment_transaction", "payment_id"):
        cr.execute(
            """
            UPDATE account_payment p
               SET transaction_id = t.id
              FROM payment_transaction t
             WHERE t.payment_id = p.id
               AND p.transaction_id IS NULL
            """
        )
        cr.execute(
            """
            SELECT t.payment_id, array_agg(t.id ORDER BY t.id)
              FROM payment_transaction t
             WHERE t.payment_id IS NOT NULL
             GROUP BY t.payment_id
            HAVING count(*) > 1
            """
        )
        if shared := cr.fetchall():
            raise ValueError(
                "account.payment.transaction_id is about to become unique, and these "
                "payments are claimed by more than one transaction: "
                + "; ".join(
                    f"payment {pid} <- transactions {txs}" for pid, txs in shared
                )
                + ". Decide which transaction owns each payment before upgrading."
            )
        # `payment_id` is a non-stored compute now; nothing drops its column.
        cr.execute('ALTER TABLE "payment_transaction" DROP COLUMN "payment_id"')

    # The plain index the column carried before is redundant once
    # `_transaction_id_uniq` covers it, and `_auto_init` does not remove one it
    # is no longer asked for.
    cr.execute('DROP INDEX IF EXISTS "account_payment__transaction_id_index"')
