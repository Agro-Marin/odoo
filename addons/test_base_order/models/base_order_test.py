from odoo import fields, models


class BaseOrderTest(models.Model):
    _name = "base.order.test"
    _inherit = [
        "mixin.order",
        "mixin.order.amount",
        "mixin.order.invoice",
        "mixin.order.merge",
    ]
    _description = "Base Order Test"

    # FIELDS

    # Order line block
    line_ids = fields.One2many(comodel_name="base.order.test.line")
    # Declared on `mixin.order` with an abstract comodel: a concrete model
    # that does not repoint it hands back `mixin.order` records.
    duplicated_order_ids = fields.Many2many(comodel_name="base.order.test")
    # References
    partner_ref = fields.Char(copy=False)

    # HELPER METHODS

    # A third order type: it behaves like a sale, and it is not sale.order.
    # Direction is shared; identity is its own -- that split is the whole
    # reason these are separate declarations.
    _order_type = "sale"
    _invoice_move_direction = "out"
    _partner_payment_term_field = "property_payment_term_id"
    _lock_setting_field = "order_lock_so"
    _product_ok_field = "sale_ok"

    _sequence_code = "base.order.test"
    _mark_sent_context_key = "mark_base_order_test_as_sent"
    _display_name_context_key = "base_order_test_show_partner_name"
    _portal_url_prefix = "base-order-test"
    _auto_lock_group = ""

    def _get_duplicate_ref_field(self):
        return "partner_ref"

    # ─── Hooks consumed by later tasks (safe generic defaults) ─────

    def _get_display_name_suffix(self):
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
