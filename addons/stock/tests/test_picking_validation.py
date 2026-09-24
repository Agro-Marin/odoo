from odoo.fields import Command
from odoo.tests import Form, TransactionCase

from odoo.addons.stock.tests.common import PickingCase


class PickingValidationCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.type_in = cls.warehouse.in_type_id
        cls.type_in.create_backorder = "ask"
        cls.product = cls.env["product.product"].create(
            {"name": "Validation kwargs product", "is_storable": True},
        )

    def _partial(self, picking_type=None, demand=10.0, done=4.0):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": (picking_type or self.type_in).id,
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": demand},
                    ),
                ],
            },
        )
        picking.action_confirm()
        picking.move_ids.quantity = done
        picking.move_ids.picked = True
        return picking

    def _picking_type(self, create_backorder):
        prefix = f"BO{create_backorder[:2].upper()}"
        return self.type_in.copy(
            {
                "name": f"Backorder {create_backorder}",
                "create_backorder": create_backorder,
                "sequence_id": self.env["ir.sequence"]
                .create({"name": prefix, "prefix": f"{prefix}/", "padding": 5})
                .id,
            },
        )


class TestTheBackorderDecisionIsAParameter(PickingValidationCase):
    def test_a_context_key_no_longer_skips_the_question(self):
        picking = self._partial()

        action = picking.with_context(skip_backorder=True).button_validate()

        self.assertIsInstance(action, dict)
        self.assertEqual(action["res_model"], "stock.backorder.confirmation")
        self.assertEqual(picking.state, "assigned")

    def test_skip_backorder_validates_and_keeps_the_rest(self):
        picking = self._partial()

        self.assertIs(picking.button_validate(skip_backorder=True), True)

        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.backorder_ids.move_ids.product_uom_qty, 6.0)

    def test_cancel_backorder_ids_cancel_the_rest(self):
        picking = self._partial()

        picking.button_validate(skip_backorder=True, cancel_backorder_ids=picking.ids)

        self.assertEqual(picking.state, "done")
        self.assertFalse(picking.backorder_ids)

    def test_a_decided_transfer_is_not_asked_about_again(self):
        decided, open_question = self._partial(), self._partial()

        action = (decided | open_question).button_validate(
            cancel_backorder_ids=decided.ids,
        )

        wizard = Form.from_action(self.env, action).save()
        self.assertEqual(wizard.pick_ids, open_question)
        wizard.process()
        self.assertEqual((decided | open_question).mapped("state"), ["done", "done"])
        self.assertFalse(decided.backorder_ids)
        self.assertTrue(open_question.backorder_ids)

    def test_the_split_is_decided_from_its_arguments(self):
        never, always, ask = (
            self._partial(self._picking_type(policy))
            for policy in ("never", "always", "ask")
        )
        pickings = never | always | ask

        to_backorder, not_to_backorder = pickings._split_backorder_pickings()
        self.assertEqual(to_backorder, always | ask)
        self.assertEqual(not_to_backorder, never)

        to_backorder, not_to_backorder = pickings._split_backorder_pickings(pickings)
        self.assertEqual(
            to_backorder,
            always,
            "an 'always' operation type keeps its backorder whatever was decided",
        )
        self.assertEqual(not_to_backorder, never | ask)

    def test_the_picking_action_done_takes_cancel_backorder(self):
        picking = self._partial()

        picking._action_done(cancel_backorder=True)

        self.assertEqual(picking.state, "done")
        self.assertFalse(picking.backorder_ids)


class TestTheBackorderWizardCarriesOnlyTheValidation(PickingValidationCase):
    def test_the_wizard_re_validates_the_transfers_it_was_opened_for(self):
        picking = self._partial()

        action = picking.button_validate()

        wizard = Form.from_action(self.env, action).save()
        self.assertEqual(wizard.validate_picking_ids, picking.ids)
        wizard.process()
        self.assertEqual(picking.state, "done")
        self.assertTrue(picking.backorder_ids)

    def test_no_backorder_from_the_wizard(self):
        picking = self._partial()

        action = picking.button_validate()

        Form.from_action(self.env, action).save().action_cancel_backorder()
        self.assertEqual(picking.state, "done")
        self.assertFalse(picking.backorder_ids)

    def test_a_caller_default_does_not_reach_the_backorder(self):
        picking = self._partial()

        action = picking.with_context(default_printed=True).button_validate()

        self.assertNotIn("default_printed", action["context"])
        wizard = (
            self.env["stock.backorder.confirmation"]
            .with_context(action["context"])
            .create({})
        )
        wizard.process()
        self.assertEqual(picking.state, "done")
        self.assertTrue(picking.backorder_ids)
        self.assertFalse(
            picking.backorder_ids.printed,
            "a default_* key of the screen the validation started from used to"
            " ride through the wizard into the backorder's create",
        )

    def test_the_wizard_ignores_default_keys_of_its_own_context(self):
        picking = self._partial()
        action = picking.button_validate()
        wizard = (
            self.env["stock.backorder.confirmation"]
            .with_context(action["context"])
            .create({})
        )

        wizard.with_context(default_printed=True).process()

        self.assertFalse(picking.backorder_ids.printed)


class TestBatchValidationIsExplicit(PickingValidationCase):
    def _batch(self, pickings):
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_ids": [Command.link(p.id) for p in pickings],
                "picking_type_id": self.type_in.id,
            },
        )
        batch.action_confirm()
        return batch

    def test_the_backorder_wizard_keeps_the_batch_it_came_from(self):
        partial = self._partial()
        untouched = self._partial(done=0.0)
        untouched.move_ids.picked = False
        batch = self._batch(partial | untouched)

        action = batch.action_done()

        wizard = Form.from_action(self.env, action).save()
        self.assertEqual(wizard.validate_kwargs["batch_id"], batch.id)
        self.assertEqual(wizard.validate_picking_ids, partial.ids)
        self.assertEqual(
            untouched.batch_id,
            batch,
            "nothing leaves the batch before the validation actually runs",
        )
        wizard.process()

        self.assertEqual(partial.state, "done")
        self.assertEqual(batch.picking_ids, partial)
        self.assertEqual(batch.state, "done")
        self.assertFalse(untouched.batch_id)
        self.assertEqual(untouched.state, "assigned")

    def test_skip_backorder_is_a_batch_parameter(self):
        picking = self._partial()
        batch = self._batch(picking)

        self.assertIs(batch.action_done(skip_backorder=True), True)

        self.assertEqual(batch.state, "done")
        self.assertTrue(picking.backorder_ids)
        self.assertFalse(picking.backorder_ids.batch_id)

    def test_a_context_key_does_not_skip_the_batch_question(self):
        batch = self._batch(self._partial())

        action = batch.with_context(skip_backorder=True).action_done()

        self.assertEqual(action["res_model"], "stock.backorder.confirmation")


class TestValidationStaysOnTheTransferItWasCalledOn(PickingCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.type_in.create_backorder = "ask"

    def _partial(self):
        picking = self._picking(quantity=10.0)
        picking.action_confirm()
        picking.move_ids.quantity = 4.0
        picking.move_ids.picked = True
        self.env.flush_all()
        return picking

    def test_a_context_cannot_redirect_the_validation_to_another_transfer(self):
        mine, bystander = self._partial(), self._partial()

        action = mine.with_context(
            button_validate_picking_ids=bystander.ids,
            default_validate_picking_ids=bystander.ids,
        ).button_validate()

        self.assertEqual(action["res_model"], "stock.backorder.confirmation")
        self.assertEqual(
            action["context"]["default_validate_picking_ids"],
            mine.ids,
            "the wizard must be handed the transfer the user opened,"
            " not whatever the incoming context named",
        )
        wizard = (
            self.env["stock.backorder.confirmation"]
            .with_context(**action["context"])
            .create({})
        )
        wizard.process()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(
            bystander.state,
            "assigned",
            "confirming a backorder dialog must not validate a transfer the user"
            " never opened -- validating moves stock and cannot be undone",
        )
        self.assertEqual(mine.state, "done")

    def test_the_wizard_re_entry_is_unaffected(self):
        picking = self._partial()
        action = picking.button_validate()
        wizard = (
            self.env["stock.backorder.confirmation"]
            .with_context(**action["context"])
            .create({})
        )
        wizard.process()
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(picking.state, "done")
        self.assertTrue(picking.backorder_ids, "the backorder is still created")

    def test_two_transfers_validated_together_keep_both(self):
        pair = self.env["stock.picking"].concat(self._partial(), self._partial())
        action = pair.button_validate()
        self.assertEqual(
            set(action["context"]["default_validate_picking_ids"]),
            set(pair.ids),
        )


class TestAMissingMailTemplateDoesNotBlockDelivery(PickingCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["stock.quant"]._update_available_quantity(
            cls.product,
            cls.warehouse.lot_stock_id,
            100,
        )
        cls.customer = cls.env["res.partner"].create(
            {"name": "Audit customer", "email": "audit@example.invalid"},
        )
        cls.env.company.stock_config_id.stock_move_email_validation = True

    def _ready_delivery(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.type_out.id,
                "partner_id": self.customer.id,
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": 2.0},
                    ),
                ],
            },
        )
        picking.action_confirm()
        picking.move_ids.quantity = 2.0
        picking.move_ids.picked = True
        self.env.flush_all()
        return picking

    def test_a_deleted_template_does_not_block_validation(self):
        self.env.company.stock_config_id.stock_mail_confirmation_template_id = False
        picking = self._ready_delivery()

        picking.button_validate(skip_backorder=True)

        self.assertEqual(
            picking.state,
            "done",
            "an absent confirmation template must not stop the goods moving;"
            " it used to raise a bare ValueError out of message_post_with_source",
        )

    def test_the_confirmation_is_still_sent_when_the_template_is_there(self):
        self.assertTrue(
            self.env.company.stock_config_id.stock_mail_confirmation_template_id
        )
        picking = self._ready_delivery()
        before = len(picking.message_ids)

        picking.button_validate(skip_backorder=True)

        self.assertEqual(picking.state, "done")
        self.assertGreater(
            len(picking.message_ids),
            before,
            "the confirmation message must still be posted",
        )
