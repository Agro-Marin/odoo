from odoo import fields, models


class BaseOrderTest(models.Model):
    _name = "base.order.test"
    _inherit = [
        "order.mixin",
        "order.amount.mixin",
        "order.invoice.mixin",
        "order.merge.mixin",
    ]
    _description = "Base Order Test"

    # FIELDS

    # Order line block
    line_ids = fields.One2many(
        comodel_name="base.order.test.line",
        inverse_name="order_id",
        string="Order Lines",
        copy=True,
    )
    # References
    partner_ref = fields.Char(copy=False)

    # HELPER METHODS

    def _get_order_type(self):
        return "sale"

    def _get_duplicate_ref_field(self):
        return "partner_ref"

    # ─── Hooks consumed by later tasks (safe generic defaults) ─────

    def _get_catalog_product_ok_field(self):
        return "sale_ok"

    def _get_display_name_suffix(self):
        # Base default context key resolves to "sale_show_partner_name"
        # (test order type is "sale").
        if not self.env.context.get(self._get_display_name_context_key()):
            return ""
        return f" - {self.partner_id.name}" if self.partner_id.name else ""

    def _get_import_template_label(self):
        return "Import Template for Base Order Test"

    def _get_import_template_path(self):
        return "/base_order_test/static/xls/base_order_test.xls"

    def _get_catalog_removed_line_price(self, product, **kwargs):
        return product.list_price

    def _get_catalog_line_price(self, line):
        return line.price_unit

    def _get_mail_subtitles(self, render_context):
        return [self.name]

    def _get_state_track_subtype_xmlid(self, init_values):
        if "state" in init_values and self.state == "done":
            return "mail.mt_note"
        return None
