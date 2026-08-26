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
