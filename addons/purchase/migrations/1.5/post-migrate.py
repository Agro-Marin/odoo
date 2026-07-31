import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Relabel bill lines recorded in a UoM cross-category with their order line.

    ``action_match_lines`` used to pair an existing bill line with an existing
    order line through a bare ``Command.link``, without checking that the two
    units share a reference.  Such a pair makes ``qty_invoiced`` degrade to an
    unconverted quantity for the rest of the order line's life, and makes the
    matching screen raise on ``_compute_product_uom_qty``.  The guard added in
    this version closes the flow; this normalizes the rows it let through.

    Raw SQL rather than the ORM: ``product_uom_id`` feeds
    ``_compute_price_unit`` (``@api.depends("product_id", "product_uom_id")``),
    so writing it through the ORM re-prices the line from the supplier record
    and rewrites ``price_subtotal``/``price_total`` on an already-posted bill.
    Measured on a production clone: 20,243.62 became 23,482.17 while ``balance``
    stayed put — an internally inconsistent entry.  A single-column UPDATE
    changes the label and nothing else, which is the whole intent here.

    Only rows whose invoiced quantity already equals the ordered quantity are
    relabeled: that equality is what proves the defect is the label and not the
    content.  A row quantified differently would *mean* something else once
    relabeled, so it is left untouched and logged for human review.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return  # fresh install: no legacy data to normalize

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
