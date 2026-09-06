"""Seed `date_promised` on orders confirmed before the field existed.

The On-Time Delivery Rate and the vendor delay report moved from
`date_commitment` to `date_promised`, which is only written when an order is
confirmed. Without this, every order already in the database reads as having no
promise, and each vendor's historical rate collapses to -1 ("no data").

The expected arrival is the best record we have of what was promised, so that is
what is copied.
"""


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        UPDATE purchase_order_line pol
           SET date_promised = pol.date_commitment
          FROM purchase_order po
         WHERE po.id = pol.order_id
           AND pol.date_promised IS NULL
           AND pol.date_commitment IS NOT NULL
           AND po.state != 'draft'
        """,
    )
    cr.execute(
        """
        UPDATE purchase_order po
           SET date_promised = sub.date_promised
          FROM (SELECT order_id, Min(date_promised) AS date_promised
                  FROM purchase_order_line
                 WHERE date_promised IS NOT NULL
                   AND display_type IS NULL
              GROUP BY order_id) sub
         WHERE po.id = sub.order_id
           AND po.date_promised IS NULL
        """,
    )
