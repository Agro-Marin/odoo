"""
Picking-Level Order Bridge

sale_stock and purchase_stock both need "when was the source order placed?"
on a transfer, and both used to declare it themselves.  Since both modules
are ``auto_install``, those two copies always coexisted and the later one in
the MRO silently won: ``delay_pass`` on a receipt answered with the sale
branch, which has no ``sale_id`` and so fell back to ``now()``.

Declared once here instead, with per-order-type hooks the bridges extend.
"""

from odoo import api, fields, models
from odoo.fields import Domain


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # ─── Fields ───────────────────────────────────────────────────

    # No ``index``: the field is not stored, and ``Registry.check_indexes`` only
    # ever builds indexes for ``field.column_type and field.store``, so the
    # ``index=True`` both bridges used to carry never created anything. Searching
    # goes through ``_search_delay_pass``, which rewrites onto the order's own
    # ``date_order`` columns and rides their indexes instead.
    delay_pass = fields.Datetime(
        compute="_compute_delay_pass",
        search="_search_delay_pass",
        copy=False,
    )

    # ─── Compute ──────────────────────────────────────────────────

    def _compute_delay_pass(self):
        for picking in self:
            picking.delay_pass = (
                picking._get_source_order_date() or fields.Datetime.now()
            )

    def _get_source_order_date(self):
        """Order date of the document this transfer originates from.

        Each order bridge extends this with an ``or super()`` chain, so a
        database carrying both sale_stock and purchase_stock answers for
        whichever order type the transfer actually came from.

        :returns: a ``Datetime``, or ``False`` when the transfer has no order
        """
        self.ensure_one()
        return False

    # ─── Search ───────────────────────────────────────────────────

    @api.model
    def _search_delay_pass(self, operator, value):
        paths = self._get_source_order_date_paths()
        if not paths:
            return Domain.FALSE
        return Domain.OR([(path, operator, value)] for path in paths)

    @api.model
    def _get_source_order_date_paths(self):
        """Field paths mirroring :meth:`_get_source_order_date`, for searching.

        Kept separate because the compute walks one record while the search
        must reach every order type at once — the disjunction of these paths
        is what ``_search_delay_pass`` builds.
        """
        return []

    # ─── Effective Transfer Date ──────────────────────────────────

    def _effective_transfer_domain(self):
        """Base condition for a transfer's ``date_done`` to count as effective.

        Each bridge narrows this with the destination usage that makes a
        transfer count for its order type, under its own name — sale keeps
        ``days_to_deliver``, purchase ``days_to_arrive``. They stay separate
        fields because they measure different things, and the narrowing is
        deliberately *not* a single overridable hook: two bridges extending one
        hook would AND sale's usage test onto purchase's as soon as both
        modules are installed, which is the shadowing failure this module
        exists to prevent.
        """
        return Domain([("state", "=", "done"), ("date_done", "!=", False)])

    def _compute_effective_transfer_date(self, field_name, domain):
        """Set ``field_name`` to ``date_done`` on the pickings matching ``domain``.

        Paired with :meth:`_search_effective_transfer_date`, which takes the
        same domain, so a bridge's compute and search cannot disagree. They did
        while each module hand-rolled the pair: the searches matched on
        ``date_done`` alone and so returned transfers whose own compute reports
        ``False`` — a receipt answering a delivery-date search.
        """
        effective = self.filtered_domain(domain)
        for picking in self:
            picking[field_name] = picking.date_done if picking in effective else False

    def _search_effective_transfer_date(self, operator, value, domain):
        """Search counterpart of :meth:`_compute_effective_transfer_date`."""
        return Domain.AND([domain, Domain("date_done", operator, value)])
