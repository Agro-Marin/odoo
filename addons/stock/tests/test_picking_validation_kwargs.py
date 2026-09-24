from odoo.fields import Command
from odoo.tests import Form, TransactionCase


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
