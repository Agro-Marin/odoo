from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestShippingPolicyLabels(TransactionCase):
    """One behaviour, one set of labels.

    `res.config.settings.default_picking_policy` does nothing but set the default
    of `sale.order.picking_policy`, so a user who reads one and then the other
    must see the same words. `stock.picking.move_type` and
    `stock.picking.type.move_type` are the same behaviour again, one layer down.
    """

    def _selection(self, model, fname):
        return dict(self.env[model]._fields[fname].selection)

    def _label(self, model, fname):
        return self.env[model]._fields[fname].string

    def test_the_settings_default_reads_like_the_order_field(self):
        self.assertEqual(
            self._selection("res.config.settings", "default_picking_policy"),
            self._selection("sale.order", "picking_policy"),
            "Settings and the order describe the same choice",
        )

    def test_both_are_called_shipping_policy(self):
        self.assertEqual(
            self._label("res.config.settings", "default_picking_policy"),
            self._label("sale.order", "picking_policy"),
            "The setting is not a different concept from the field it defaults",
        )

    def test_the_order_agrees_with_the_transfer_it_creates(self):
        """Guard against a future half-migration.

        This is why the settings field was aligned down to these words rather
        than up to upstream's newer "..., with back orders": `stock` and
        `point_of_sale` still use these, and they are outside this batch.
        """
        self.assertEqual(
            self._selection("sale.order", "picking_policy"),
            self._selection("stock.picking", "move_type"),
            "The order's policy and the transfer's are one behaviour",
        )
