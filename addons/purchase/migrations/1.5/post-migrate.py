import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Relabel bill lines recorded in a UoM cross-category with their order line.

    :param cr: database cursor
    :param version: module version being upgraded from
    """
    if not version:
        return

    cross_category = """
        FROM account_move_line_purchase_order_line_rel rel
        JOIN account_move_line aml ON aml.id = rel.move_line_id
        JOIN purchase_order_line pol ON pol.id = rel.order_line_id
        JOIN uom_uom au ON au.id = aml.product_uom_id
        JOIN uom_uom pu ON pu.id = pol.product_uom_id
        WHERE split_part(au.parent_path, '/', 1) <> split_part(pu.parent_path, '/', 1)
    """

    # Report before touching anything: a quantity mismatch means the pairing
    # itself is suspect, so it needs a human, not an UPDATE.
    cr.execute(
        f"""
        SELECT aml.id, pol.id, aml.quantity, pol.product_qty
        {cross_category}
          AND aml.quantity IS DISTINCT FROM pol.product_qty
        """
    )
    if unresolved := cr.fetchall():
        _logger.warning(
            "Cross-category UoM left untouched on %s bill line(s): the invoiced "
            "quantity differs from the ordered one, so relabeling would change "
            "what the document states. Needs review — (aml, pol, qty, ordered): %s",
            len(unresolved),
            unresolved,
        )

    # Raw SQL, not the ORM: `product_uom_id` feeds `_compute_price_unit`, which
    # would re-price an already-posted bill from the supplier record.
    cr.execute(
        f"""
        UPDATE account_move_line SET product_uom_id = sub.pol_uom_id
        FROM (
            SELECT aml.id AS aml_id, pol.product_uom_id AS pol_uom_id
            {cross_category}
              AND aml.quantity = pol.product_qty
        ) AS sub
        WHERE account_move_line.id = sub.aml_id
        """
    )
    if cr.rowcount:
        _logger.info(
            "Relabeled %s bill line(s) to their order line's unit of measure.",
            cr.rowcount,
        )
