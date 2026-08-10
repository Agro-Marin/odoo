# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged

# base_order provides abstract mixins and two order-shaped extensions of
# non-order models (res.partner, product.product). They are exercised through
# their concrete consumers — sale.order and purchase.order both compose them —
# so each test here asserts the *same* behaviour on both order types. That is
# the point of the module: where the two used to hold separate copies of a
# feature, they must now agree.


@tagged("post_install", "-at_install")
class TestOrderSharedFeatures(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Without a layout, ``report_action`` wraps the report in the "choose
        # your document layout" dialog instead of returning it.
        cls.env.company.external_report_layout_id = cls.env.ref(
            "web.external_layout_standard",
        )
        cls.partner = cls.env["res.partner"].create({"name": "Counterparty"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Shared Item",
                "list_price": 100.0,
                "standard_price": 60.0,
                "sale_ok": True,
                "purchase_ok": True,
            },
        )

    def _orders(self):
        """One draft order of each type, both carrying ``self.product``."""
        return {
            "sale.order": self.env["sale.order"].create(
                {
                    "partner_id": self.partner.id,
                    "line_ids": [(0, 0, {"product_id": self.product.id})],
                },
            ),
            "purchase.order": self.env["purchase.order"].create(
                {
                    "partner_id": self.partner.id,
                    "line_ids": [(0, 0, {"product_id": self.product.id})],
                },
            ),
        }

    # ------------------------------------------------------------------
    # product.product — catalog "already on this order" flag
    # ------------------------------------------------------------------

    def test_is_in_order_is_true_for_the_order_in_context(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                field = f"is_in_{order._get_order_type()}_order"
                product = self.product.with_context(order_id=order.id)
                product.invalidate_recordset([field])
                self.assertTrue(product[field])

    def test_is_in_order_is_false_without_an_order_in_context(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                field = f"is_in_{order._get_order_type()}_order"
                self.product.invalidate_recordset([field])
                self.assertFalse(self.product[field])

    def test_search_is_in_order_finds_the_products_on_that_order(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                field = f"is_in_{order._get_order_type()}_order"
                found = (
                    self.env["product.product"]
                    .with_context(order_id=order.id)
                    .search([(field, "in", [True])])
                )
                self.assertIn(self.product, found)

    def test_search_is_in_order_matches_nothing_without_an_order(self):
        """No order in context must mean "no products", not "every product".

        Sale built the domain from ``context.get("order_id", "")``, which
        searches lines whose ``order_id`` equals the empty string — the
        opposite of the intent, and a query issued for nothing.
        """
        self._orders()
        for order_type in ("sale", "purchase"):
            with self.subTest(order_type=order_type):
                self.assertFalse(
                    self.env["product.product"].search(
                        [(f"is_in_{order_type}_order", "in", [True])],
                    ),
                )

    # ------------------------------------------------------------------
    # order.line.amount.mixin — discounted unit price
    # ------------------------------------------------------------------

    def test_price_discounted_matches_the_stored_field(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                line = order.line_ids[0]
                line.write({"price_unit": 200.0, "discount": 25.0})
                self.assertEqual(line._get_price_discounted(), 150.0)
                self.assertEqual(line.price_unit_discounted_taxexc, 150.0)

    # ------------------------------------------------------------------
    # order.mixin — send / print tracking
    # ------------------------------------------------------------------

    def test_mark_as_sent_sets_the_flag_and_counts_the_send(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                self.assertFalse(order.sent)
                self.assertEqual(order.count_sent, 0)
                order._mark_as_sent()
                self.assertTrue(order.sent)
                self.assertEqual(order.count_sent, 1)
                order._mark_as_sent()
                self.assertEqual(order.count_sent, 2)

    def test_print_flags_draft_orders_and_always_counts(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                order.action_print_order()
                self.assertTrue(order.printed_before)
                self.assertEqual(order.count_print, 1)

    def test_print_of_a_confirmed_order_counts_but_does_not_flag(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                order.action_confirm()
                order.action_print_order()
                self.assertFalse(order.printed_before)
                self.assertEqual(order.count_print, 1)

    def test_print_returns_the_report_action_of_each_order_type(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                action = order.action_print_order()
                self.assertEqual(action["type"], "ir.actions.report")
                self.assertEqual(
                    action["report_name"],
                    self.env.ref(order._get_print_report_xmlid()).report_name,
                )

    # ------------------------------------------------------------------
    # order.mixin — mail composer action
    # ------------------------------------------------------------------

    def test_send_by_email_opens_the_composer_with_the_template(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                action = order._action_send_by_email()
                ctx = action["context"]
                self.assertEqual(action["res_model"], "mail.compose.message")
                self.assertEqual(ctx["default_model"], order._name)
                self.assertEqual(ctx["default_res_ids"], order.ids)
                self.assertEqual(ctx["default_composition_mode"], "comment")
                self.assertTrue(ctx["force_email"])
                self.assertEqual(
                    ctx["default_template_id"],
                    order._get_mail_template().id,
                )
                self.assertTrue(ctx[order._get_mark_sent_context_key()])

    def test_send_by_email_switches_to_mass_mail_for_several_orders(self):
        """Several orders render one template each, so the single-order keys
        (``force_email``, the template, the mark-as-sent flag) must not be set."""
        orders = self.env["sale.order"].create(
            [
                {
                    "partner_id": self.partner.id,
                    "line_ids": [(0, 0, {"product_id": self.product.id})],
                },
            ]
            * 2,
        )
        ctx = orders._action_send_by_email()["context"]
        self.assertEqual(ctx["default_composition_mode"], "mass_mail")
        self.assertNotIn("force_email", ctx)
        self.assertNotIn("default_template_id", ctx)
        self.assertNotIn(orders._get_mark_sent_context_key(), ctx)

    def test_send_by_email_opens_in_the_template_language(self):
        """The composer follows the template's own ``lang``.

        Purchase resolved the language but read ``model_description`` off the
        untranslated recordset beforehand, so the one string the switch existed
        for was still built in the user's language; sale never resolved it at
        all.
        """
        self.env["res.lang"]._activate_lang("fr_FR")
        for order in self._orders().values():
            with self.subTest(model=order._name):
                template = order._get_mail_template()
                template.lang = "fr_FR"
                ctx = order._action_send_by_email()["context"]
                self.assertEqual(ctx["lang"], "fr_FR")

    def test_send_by_email_keeps_the_user_language_without_a_template_lang(self):
        for order in self._orders().values():
            with self.subTest(model=order._name):
                order._get_mail_template().lang = False
                ctx = order.with_context(lang="en_US")._action_send_by_email()[
                    "context"
                ]
                self.assertEqual(ctx["lang"], "en_US")
