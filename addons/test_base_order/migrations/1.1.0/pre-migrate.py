"""Release the `sale.order` sequence code this module used to squat on.

`mixin.order` built its sequence code as f"{order_type}.order", so a third
order type had no way to name its own counter and this module registered
`code = 'sale.order'`. Being company-scoped it shadowed `sale.seq_sale_order`,
and every sales order created afterwards was named with the BOT prefix off the
test module's counter.

The record was also company-scoped, which is *how* it won: a company-scoped
sequence shadows a global one of the same code. It is global now, like sale's
and purchase's.

The XML now declares `base.order.test`, but the record was loaded under
`noupdate`, which is recorded per-record in `ir_model_data` and is not lifted by
editing the file. Clear the flag and rewrite the code here so an existing
database is repaired rather than left holding sale's names hostage.
"""


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        UPDATE ir_sequence s
           SET code = 'base.order.test'
          FROM ir_model_data d
         WHERE d.model = 'ir.sequence'
           AND d.module = 'test_base_order'
           AND d.name = 'seq_base_order_test'
           AND d.res_id = s.id
           AND s.code = 'sale.order'
        """,
    )
    cr.execute(
        """
        UPDATE ir_sequence s
           SET company_id = NULL
          FROM ir_model_data d
         WHERE d.model = 'ir.sequence'
           AND d.module = 'test_base_order'
           AND d.name = 'seq_base_order_test'
           AND d.res_id = s.id
        """,
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = FALSE
         WHERE model = 'ir.sequence'
           AND module = 'test_base_order'
           AND name = 'seq_base_order_test'
        """,
    )
