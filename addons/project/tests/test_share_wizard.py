from odoo import Command
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestShareWizardAppliesOnConfirm(TestProjectCommon):
    def _wizard(self, project, partner, access_mode="edit"):
        return self.env["project.share.wizard"].create(
            {
                "res_model": "project.project",
                "res_id": project.id,
                "collaborator_ids": [
                    Command.create(
                        {"partner_id": partner.id, "access_mode": access_mode}
                    )
                ],
            }
        )

    def test_saving_the_dialog_grants_nothing(self) -> None:
        project = self.env["project.project"].create(
            {"name": "Shared", "privacy_visibility": "portal"}
        )
        self._wizard(project, self.user_portal.partner_id)
        self.assertFalse(project.collaborator_ids)

    def test_sharing_grants_access(self) -> None:
        project = self.env["project.project"].create(
            {"name": "Shared", "privacy_visibility": "portal"}
        )
        self._wizard(project, self.user_portal.partner_id).action_send_mail()
        self.assertEqual(
            project.collaborator_ids.partner_id, self.user_portal.partner_id
        )

    def test_emptying_the_list_still_revokes(self) -> None:
        project = self.env["project.project"].create(
            {"name": "Shared", "privacy_visibility": "portal"}
        )
        self._wizard(project, self.user_portal.partner_id).action_send_mail()
        self.assertTrue(project.collaborator_ids)

        revoke = self.env["project.share.wizard"].create(
            {
                "res_model": "project.project",
                "res_id": project.id,
                "collaborator_ids": [],
            }
        )
        revoke.action_share_record()
        self.assertFalse(project.collaborator_ids)

    def test_applying_twice_is_a_no_op(self) -> None:
        project = self.env["project.project"].create(
            {"name": "Shared", "privacy_visibility": "portal"}
        )
        wizard = self._wizard(project, self.user_portal.partner_id)
        wizard.action_send_mail()
        wizard.action_send_mail()
        self.assertEqual(len(project.collaborator_ids), 1)


@tagged("post_install", "-at_install")
class TestCollaboratorRulesLetAManagerShare(TestProjectCommon):
    def test_a_manager_can_share_a_project_they_neither_follow_nor_own(self) -> None:
        # project.collaborator carries the comp / visibility / manager triad that
        # project.risk and project.gate carry. The manager member is what makes
        # the pair work: an ir.rule with no perm_* fields governs create as well
        # as read, group_project_manager implies group_project_user, and rules of
        # different groups OR together -- so without an unrestricted manager rule
        # the read-scoping visibility rule also blocks a manager from CREATING a
        # collaborator on a project they do not follow. That is every project the
        # setUpClass of an HttpCase builds, which is how it reached the sharing
        # tours rather than a unit test.
        project = (
            self.env["project.project"]
            .with_user(self.env.ref("base.user_root"))
            .create({"name": "Owned by nobody", "privacy_visibility": "portal"})
        )
        project.message_unsubscribe(partner_ids=project.message_partner_ids.ids)
        manager = self.user_projectmanager
        self.assertNotIn(manager.partner_id, project.message_partner_ids)
        self.assertNotEqual(project.user_id, manager)

        project.with_user(manager).write(
            {
                "collaborator_ids": [
                    Command.create({"partner_id": self.user_portal.partner_id.id})
                ]
            }
        )
        self.assertEqual(
            project.collaborator_ids.partner_id, self.user_portal.partner_id
        )
