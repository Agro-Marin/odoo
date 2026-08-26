from odoo.tests import TransactionCase, tagged

#: Every model that mixes in `mixin.order`, and the line model beside it.
ORDER_MODELS = ["sale.order", "purchase.order", "base.order.test"]
ORDER_LINE_MODELS = ["sale.order.line", "purchase.order.line", "base.order.test.line"]

#: What `mixin.order` reads off a concrete order model instead of deriving it
#: from the order type. `_auto_lock_group` is deliberately absent: empty is a
#: meaningful value there, and `base.order.test` uses it.
ORDER_DECLARATIONS = [
    "_order_type",
    "_sequence_code",
    "_invoice_move_direction",
    "_partner_payment_term_field",
    "_lock_setting_field",
    "_mark_sent_context_key",
    "_display_name_context_key",
    "_portal_url_prefix",
    "_product_ok_field",
]
LINE_DECLARATIONS = [
    "_order_type",
    "_product_ok_field",
    "_analytic_business_domain",
    "_product_tax_field",
]


@tagged("post_install", "-at_install")
class TestOrderTypeDeclarations(TransactionCase):
    """The contract that replaced the order-type switches.

    `mixin.order` used to answer these by branching on `_get_order_type()`,
    which meant a third order type silently received the purchase answer for
    every one of them. They are declarations now, and this asserts that each
    concrete model actually makes them -- an omission is a class attribute
    left empty, which no other test would notice.
    """

    def test_every_order_model_declares_what_the_mixin_reads(self):
        for model_name in ORDER_MODELS:
            model = self.env[model_name]
            for attribute in ORDER_DECLARATIONS:
                with self.subTest(model=model_name, attribute=attribute):
                    self.assertTrue(
                        getattr(model, attribute, ""),
                        f"{model_name} does not declare {attribute}",
                    )

    def test_every_order_line_model_declares_what_the_mixin_reads(self):
        for model_name in ORDER_LINE_MODELS:
            model = self.env[model_name]
            for attribute in LINE_DECLARATIONS:
                with self.subTest(model=model_name, attribute=attribute):
                    self.assertTrue(
                        getattr(model, attribute, ""),
                        f"{model_name} does not declare {attribute}",
                    )

    def test_order_type_is_a_direction_and_only_a_direction(self):
        for model_name in ORDER_MODELS + ORDER_LINE_MODELS:
            with self.subTest(model=model_name):
                self.assertIn(self.env[model_name]._order_type, ("sale", "purchase"))

    def test_price_direction_agrees_with_the_order_type(self):
        for model_name in ORDER_LINE_MODELS:
            model = self.env[model_name]
            with self.subTest(model=model_name):
                expected = 1 if model._order_type == "sale" else -1
                self.assertEqual(model._price_direction, expected)

    def test_invoice_move_direction_agrees_with_the_order_type(self):
        for model_name in ORDER_MODELS + ORDER_LINE_MODELS:
            model = self.env[model_name]
            if not getattr(model, "_invoice_move_direction", ""):
                continue
            with self.subTest(model=model_name):
                expected = "out" if model._order_type == "sale" else "in"
                self.assertEqual(model._invoice_move_direction, expected)

    def test_a_model_that_declares_no_order_type_is_refused(self):
        order = self.env["base.order.test"]
        with self.subTest("order"), self.assertRaises(NotImplementedError):
            order.with_context(_=1).__class__._order_type = ""
            try:
                order._get_order_type()
            finally:
                order.__class__._order_type = "sale"

    def test_no_two_order_models_share_a_sequence_code(self):
        """The defect this contract exists to prevent.

        `base.order.test` once declared `code = 'sale.order'` on its own
        `ir.sequence`, because the mixin built that code from the order type
        and left it no way to name its own. Being company-scoped it shadowed
        sale's, and every sales order created afterwards was named off the
        test module's counter.
        """
        codes = [self.env[name]._sequence_code for name in ORDER_MODELS]

        self.assertEqual(
            len(codes),
            len(set(codes)),
            f"order models share a sequence code: {codes}",
        )

    def test_each_order_model_draws_names_from_its_own_sequence(self):
        """Names must carry the prefix of the model's *own* sequence.

        Asserting only that the three names differ is not enough: three models
        all drawing from one counter also produce three different names. The
        prefix is what says which counter answered.
        """
        for model_name in ORDER_MODELS:
            model = self.env[model_name]
            sequence = (
                self.env["ir.sequence"]
                .sudo()
                .search([("code", "=", model._sequence_code)], limit=1)
            )
            order = model.create({"partner_id": self.env.user.partner_id.id})
            with self.subTest(model=model_name):
                self.assertTrue(sequence, f"no sequence for {model._sequence_code}")
                self.assertNotEqual(order.name, "New")
                self.assertTrue(
                    order.name.startswith(sequence.prefix),
                    f"{model_name} was named {order.name!r}, which does not come "
                    f"from its own sequence (prefix {sequence.prefix!r})",
                )

    def test_sequence_codes_resolve_to_exactly_one_sequence(self):
        for model_name in ORDER_MODELS:
            code = self.env[model_name]._sequence_code
            with self.subTest(model=model_name, code=code):
                sequences = self.env["ir.sequence"].sudo().search([("code", "=", code)])
                self.assertEqual(
                    len(sequences),
                    1,
                    f"{code} resolves to {len(sequences)} sequences: "
                    f"{sequences.mapped('prefix')}",
                )

    def test_every_order_sequence_is_global(self):
        """A company-scoped sequence shadows a global one of the same code.

        That is the mechanism by which this module's sequence took over
        `sale.order`, and it also leaves every other company without a
        sequence at all, so orders created there come out unnamed.
        """
        for model_name in ORDER_MODELS:
            code = self.env[model_name]._sequence_code
            sequences = self.env["ir.sequence"].sudo().search([("code", "=", code)])
            with self.subTest(model=model_name, code=code):
                self.assertTrue(sequences)
                self.assertFalse(
                    sequences.company_id,
                    f"{code} is scoped to {sequences.company_id.mapped('name')}, "
                    f"so it shadows any global sequence of the same code and "
                    f"leaves other companies unnamed",
                )

    def test_an_order_created_in_a_second_company_is_still_named(self):
        second = self.env["res.company"].create({"name": "Second Co"})
        self.env.user.company_ids = [(4, second.id)]
        partner = self.env["res.partner"].create({"name": "Second Co Partner"})

        order = (
            self.env["base.order.test"]
            .with_company(second)
            .create({"partner_id": partner.id, "company_id": second.id})
        )

        self.assertNotEqual(order.name, "New")
        self.assertTrue(order.name)
