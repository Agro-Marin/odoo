import logging

_logger = logging.getLogger(__name__)

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
