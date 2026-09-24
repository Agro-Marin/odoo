from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user
from odoo.tools import mute_logger


class TestVerbs(TransactionCase):
    """A verb is an operation the policy grants like create, read, write, unlink.

    `test_ir_access.document` declares `post`: its door is `action_post`, its
    checkpoints `_check_postable` and `_post_entries`, and it is the move of
    `state` into `posted`.
    Every internal user may write a document; only administrators may post one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clerk = new_test_user(cls.env, login="verb_clerk", groups="base.group_user")
        cls.admin = new_test_user(
            cls.env, login="verb_admin", groups="base.group_user,base.group_system"
        )
        cls.Document = cls.env["test_ir_access.document"]

    def _document(self, **vals):
        return self.Document.create({"name": "Verb", **vals})

    def test_a_verb_is_granted_by_its_rows(self):
        document = self._document()
        self.assertFalse(document.with_user(self.clerk).has_access("post"))
        self.assertTrue(document.with_user(self.clerk).has_access("write"))
        self.assertTrue(document.with_user(self.admin).has_access("post"))
        self.assertTrue(document.has_access("post"), "the superuser holds every verb")

    def test_the_door_refuses_who_does_not_hold_the_verb(self):
        document = self._document()
        with (
            mute_logger("odoo.addons.base.models.ir_access"),
            self.assertRaises(AccessError) as caught,
        ):
            document.with_user(self.clerk).action_post()
        self.assertIn("post", str(caught.exception))
        self.assertEqual(document.state, "draft")
        document.with_user(self.admin).action_post()
        self.assertEqual(document.state, "posted")

    def test_writing_the_state_is_the_verb(self):
        document = self._document()
        with (
            mute_logger("odoo.addons.base.models.ir_access"),
            self.assertRaises(AccessError),
        ):
            document.with_user(self.clerk).write({"state": "posted"})
        document.with_user(self.clerk).write({"audit": "a clerk may still edit it"})
        document.with_user(self.admin).write({"state": "posted"})
        self.assertEqual(document.state, "posted")

    def test_creating_in_the_state_is_the_verb(self):
        with (
            mute_logger("odoo.addons.base.models.ir_access"),
            self.assertRaises(AccessError),
        ):
            self.Document.with_user(self.clerk).create(
                {"name": "Born posted", "state": "posted"}
            )
        born = self.Document.with_user(self.admin).create(
            {"name": "Born posted", "state": "posted"}
        )
        self.assertEqual(born.state, "posted")

    def test_a_verb_never_outruns_the_operation_it_requires(self):
        guard = self.env["ir.access"].create(
            {
                "name": "document: only drafts named Open are written",
                "model_id": self.env["ir.model"]._get_id("test_ir_access.document"),
                "group_id": self.env.ref("base.group_everyone").id,
                "kind": "guard",
                "operation": "u",
                "domain": "[('name', '=', 'Open')]",
            }
        )
        closed = self._document(name="Closed")
        opened = self._document(name="Open")
        documents = (closed | opened).with_user(self.admin)
        self.assertEqual(documents._filtered_access("post"), opened)
        guard.unlink()

    def test_the_door_admits_its_call_so_the_checkpoint_is_not_asked_again(self):
        calls = []
        document = self._document().with_context(verb_calls=calls)
        document.with_user(self.admin).action_post()
        self.assertEqual(calls, [("door", "post", document.ids)])

    def test_a_checkpoint_reached_by_another_door_is_asked(self):
        calls = []
        document = self._document().with_context(verb_calls=calls)
        document.with_user(self.admin)._check_postable()
        self.assertEqual(calls, [("checkpoint", "post", document.ids)])
        with (
            mute_logger("odoo.addons.base.models.ir_access"),
            self.assertRaises(AccessError),
        ):
            document.with_user(self.clerk)._check_postable()

    def test_a_checkpoint_admits_the_rest_of_its_call(self):
        calls = []
        document = self._document().with_context(verb_calls=calls)
        document.with_user(self.admin)._post_entries()
        self.assertEqual(document.state, "posted")
        self.assertEqual(
            calls,
            [("checkpoint", "post", document.ids)],
            "the state the checkpoint's own call writes is not asked again",
        )

    def test_a_row_names_only_the_verbs_its_model_declares(self):
        with self.assertRaises(ValidationError):
            self.env["ir.access"].create(
                {
                    "name": "item: an undeclared verb",
                    "model_id": self.env["ir.model"]._get_id("test_ir_access.item"),
                    "group_id": self.env.ref("base.group_user").id,
                    "kind": "permission",
                    "verbs": "post",
                }
            )

    def test_an_undeclared_verb_is_no_operation(self):
        with self.assertRaises(ValueError):
            self._document().with_user(self.clerk).check_access("publish")

    def test_every_declared_verb_is_granted_by_some_row(self):
        rows = self.env["ir.access"].search([("verbs", "!=", False)])
        governed = {
            (row.model_id.model, verb)
            for row in rows.filtered(lambda row: row.kind == "permission")
            for verb in row.verbs.split(",")
        }
        declared = {
            (model_name, verb)
            for model_name, verbs in self.env.registry.model_verbs.items()
            for verb in verbs
        }
        self.assertFalse(
            declared - governed,
            "a declared verb nobody holds refuses everyone but the superuser",
        )
