"""Backfill res_partner.user_purchase_id from parent contacts (1.6).

``user_purchase_id`` gains the parent-inheritance rule that ``res.partner``'s
``user_id`` has carried in ``base`` all along: a contact that is not itself a
company, and has no buyer of its own, takes its parent's.

Adding a ``compute`` to a column that already exists does not recompute the
rows already in it — the ORM only recomputes a stored computed field when it
first creates the column — so without this every contact created before the
upgrade keeps a NULL buyer until something happens to write the record.

The UPDATE is the compute's own rule expressed in SQL. It repeats until it
stops changing rows so that a buyer set on a company cascades all the way down
a multi-level contact tree, which is what recomputation would do (each level's
value is inherited once its own parent has been resolved).

Idempotent: a second run matches nothing, because every row it would touch now
has a value.
"""

import logging

_logger = logging.getLogger(__name__)

# Contact trees are shallow; this only bounds the loop if parent_id ever
# contains a cycle, which would otherwise spin forever.
MAX_PASSES = 20


def migrate(cr, version):
    total = 0
    for _pass in range(MAX_PASSES):
        cr.execute(
            """
            UPDATE res_partner child
               SET user_purchase_id = parent.user_purchase_id
              FROM res_partner parent
             WHERE child.parent_id = parent.id
               AND child.user_purchase_id IS NULL
               AND parent.user_purchase_id IS NOT NULL
               AND COALESCE(child.is_company, FALSE) = FALSE
            """
        )
        if not cr.rowcount:
            break
        total += cr.rowcount
    else:
        _logger.warning(
            "purchase: user_purchase_id backfill hit %s passes without settling; "
            "res_partner.parent_id may contain a cycle",
            MAX_PASSES,
        )

    if total:
        _logger.info(
            "purchase: inherited user_purchase_id onto %s contact(s) from their parent",
            total,
        )
