import collections

from odoo import api, fields, models
from odoo.fields import Domain


class ProductTemplate(models.Model):
    _name = "product.template"
    _inherit = ["product.template", "mixin.mrp.product"]

    _mrp_product_field = "product_tmpl_id"
    _mrp_bom_field = "bom_ids"

    bom_line_ids = fields.One2many("mrp.bom.line", "product_tmpl_id", "BoM Components")
    bom_ids = fields.One2many("mrp.bom", "product_tmpl_id", "Bill of Materials")

    def _get_mrp_variants(self):
        return self.product_variant_ids

    # No `@api.depends` here, and it is not an oversight. Declaring
    # `depends("bom_ids")` was measured against this exact method with the
    # dependency stripped back off: create a BoM, archive one, unlink one,
    # repoint one at another template, repoint a line at another component --
    # every read agreed to the record, with and without, at the same query
    # count and the same number of recomputations (0). The one case that is
    # stale, a BoM that starts producing this template as a *byproduct*, is
    # stale both ways and has no reverse relation to hang a dependency on. A
    # declaration that changes nothing is a claim the code does not keep.
    def _compute_bom_count(self):
        bom_ids_by_template = collections.defaultdict(set)
        for template, bom_ids in self.env["mrp.bom"]._read_group(
            [("product_tmpl_id", "in", self.ids)],
            ["product_tmpl_id"],
            ["id:array_agg"],
        ):
            bom_ids_by_template[template.id].update(bom_ids)
        for product, bom_ids in self.env["mrp.bom.byproduct"]._read_group(
            [("product_id.product_tmpl_id", "in", self.ids)],
            ["product_id"],
            ["bom_id:array_agg"],
        ):
            bom_ids_by_template[product.product_tmpl_id.id].update(bom_ids)
        for product in self:
            product.bom_count = len(bom_ids_by_template.get(product.id, ()))

    @api.depends_context("company")
    def _compute_is_kit(self):
        # `_read_group`, not `search_read`: the set of template ids is all that
        # is wanted, and reading `product_tmpl_id` through `search_read` renders
        # a display name for every BoM row only to throw it away.
        Bom = self.env["mrp.bom"].sudo()
        kit_template_ids = {
            template.id
            for [template] in Bom._read_group(
                Bom._get_kit_domain() & Domain("product_tmpl_id", "in", self.ids),
                ["product_tmpl_id"],
            )
        }
        for template in self:
            template.is_kit = template.id in kit_template_ids

    def _search_is_kit(self, operator, value):
        if operator != "in" or set(value) != {True}:
            return NotImplemented
        Bom = self.env["mrp.bom"].sudo()
        bom_query = Bom._search(Bom._get_kit_domain())
        return [("id", "in", bom_query.subselect("product_tmpl_id"))]

    def action_archive(self):
        still_used = self._get_still_used_bom_lines()
        res = super().action_archive()
        return still_used._get_still_used_notification() or res

    def _compute_show_qty_status_button(self):
        super()._compute_show_qty_status_button()
        for template in self:
            if template.is_kit:
                template.show_on_hand_qty_status_button = (
                    template.product_variant_count <= 1
                )
                template.show_forecasted_qty_status_button = False

    def _should_open_product_quants(self):
        return super()._should_open_product_quants() or self.is_kit

    def _compute_mrp_product_qty(self):
        for template in self:
            template.mrp_product_qty = template.uom_id.round(
                sum(template.product_variant_ids.mapped("mrp_product_qty"))
            )
