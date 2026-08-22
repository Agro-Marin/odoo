from odoo import Command
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_documents_common import TransactionCaseDocuments


@tagged("post_install", "-at_install")
class TestDocumentsEmbeddedActions(TransactionCaseDocuments):

    def _server_action(self, **extra):
        return self.env["ir.actions.server"].create(
            {
                "name": extra.pop("name", "dedup action"),
                "model_id": self.env["ir.model"]._get_id("documents.document"),
                "state": "code",
                "code": "pass",
                "usage": "ir_actions_server",
                **extra,
            }
        )

    def test_cannot_pin_an_action_the_listing_would_hide(self):
        parent = self._server_action(name="dedup parent")
        child = self._server_action(name="dedup child", parent_id=parent.id)
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "embed folder",
            }
        )

        with self.assertRaises(UserError):
            self.env["documents.document"].action_folder_embed_action(
                folder.id, child.id
            )
        self.assertFalse(
            self.env["ir.embedded.actions"].search_count(
                [
                    ("parent_res_id", "=", folder.id),
                    ("action_id", "=", child.id),
                ]
            ),
            "a refused pin must leave no orphan row behind",
        )

    def test_a_listable_action_still_pins_and_appears(self):
        action = self._server_action(name="dedup pinnable")
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "embed folder ok",
            }
        )
        self.env["documents.document"].action_folder_embed_action(folder.id, action.id)
        listed = self.env["documents.document"]._get_folder_embedded_actions(folder.ids)
        self.assertIn(
            action.id,
            listed.get(folder.id, self.env["ir.embedded.actions"]).action_id.ids,
        )


@tagged("post_install", "-at_install")
class TestDocumentsAutomationAvailability(TransactionCaseDocuments):
    def test_check_automation_available_returns_bool(self):
        result = (
            self.env["documents.document"]
            .with_user(self.doc_user)
            .check_automation_available()
        )
        self.assertIsInstance(result, bool)


@tagged("post_install", "-at_install")
class TestDocumentsEmbeddedActionsGc(TransactionCaseDocuments):

    def test_gc_keeps_pins_of_actions_the_vacuum_user_cannot_see(self):
        group = self.env["res.groups"].create({"name": "gc probe group"})
        folder = self.env["documents.document"].create(
            {"name": "gc probe folder", "type": "folder"}
        )
        action = self.env["ir.actions.server"].create(
            {
                "name": "gc probe action",
                "model_id": self.env["ir.model"]._get_id("documents.document"),
                "type": "ir.actions.server",
                "group_ids": [Command.set(group.ids)],
                "update_path": "sequence",
                "usage": "ir_actions_server",
                "state": "object_write",
                "value": "1",
            }
        )
        pinner = self.env.ref("base.user_admin")
        pinner.group_ids = [Command.link(group.id)]
        self.env["documents.document"].with_user(pinner).action_folder_embed_action(
            folder.id, action.id
        )
        pinned = self.env["ir.embedded.actions"].search(
            [
                ("parent_res_model", "=", "documents.document"),
                ("parent_res_id", "=", folder.id),
                ("action_id", "=", action.id),
            ]
        )
        self.assertTrue(pinned, "the fixture must actually pin something")

        vacuum_user = self.env.ref("base.user_root")
        self.assertNotIn(
            group,
            vacuum_user.all_group_ids,
            "the test only means anything while the vacuum user lacks the group",
        )
        self.env["ir.embedded.actions"].with_user(vacuum_user)._gc_documents_obsolete()

        self.assertTrue(
            pinned.exists(),
            "a pin was deleted by a vacuum that merely could not see the action",
        )

    def test_gc_still_removes_a_child_action_pin(self):
        parent = self.env["ir.actions.server"].create(
            {
                "name": "gc parent action",
                "model_id": self.env["ir.model"]._get_id("documents.document"),
                "type": "ir.actions.server",
                "update_path": "sequence",
                "usage": "ir_actions_server",
                "state": "object_write",
                "value": "1",
            }
        )
        child = self.env["ir.actions.server"].create(
            {
                "name": "gc child action",
                "model_id": self.env["ir.model"]._get_id("documents.document"),
                "type": "ir.actions.server",
                "update_path": "sequence",
                "usage": "ir_actions_server",
                "state": "object_write",
                "value": "1",
            }
        )
        folder = self.env["documents.document"].create(
            {"name": "gc child folder", "type": "folder"}
        )
        self.env["documents.document"].action_folder_embed_action(folder.id, child.id)
        pinned = self.env["ir.embedded.actions"].search(
            [
                ("parent_res_model", "=", "documents.document"),
                ("parent_res_id", "=", folder.id),
                ("action_id", "=", child.id),
            ]
        )
        self.assertTrue(pinned)
        child.parent_id = parent
        removed, more = self.env["ir.embedded.actions"]._gc_documents_obsolete()
        self.assertFalse(pinned.exists(), "an unexecutable pin must be collected")
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(more, "one small batch cannot be a full one")
