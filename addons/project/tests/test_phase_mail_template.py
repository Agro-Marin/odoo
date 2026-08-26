from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestPhaseMailTemplateModel(TestProjectCommon):
    def setUp(self):
        super().setUp()
        self.env["res.config.settings"].create({"group_project_stages": True}).execute()
        self.phase = self.env.ref("project.project_phase_1")
        self.foreign_template = self.env["mail.template"].create(
            {
                "name": "Foreign",
                "subject": "S",
                "body_html": '<p>RENDERED-FROM: <t t-out="object.name"/></p>',
                "model_id": self.env.ref("project.model_project_phase").id,
            }
        )
        self.project_template = self.env["mail.template"].create(
            {
                "name": "Proper",
                "subject": "S",
                "body_html": '<p>PROJECT: <t t-out="object.name"/></p>',
                "model_id": self.env.ref("project.model_project_project").id,
            }
        )

    def test_a_foreign_model_template_is_refused(self):
        with self.assertRaises(ValidationError):
            self.phase.mail_template_id = self.foreign_template

    def test_a_project_template_is_accepted(self):
        self.phase.mail_template_id = self.project_template
        self.assertEqual(self.phase.mail_template_id, self.project_template)

    def test_a_foreign_template_already_stored_leaks_nothing(self):
        self.env.cr.execute(
            "UPDATE project_phase SET mail_template_id=%s WHERE id=%s",
            (self.foreign_template.id, self.phase.id),
        )
        self.phase.invalidate_recordset(["mail_template_id"])

        project = self.env["project.project"].create(
            {"name": "ProjA", "privacy_visibility": "followers"}
        )
        self.env.flush_all()
        self.env.cr.flush()
        self.env.cr.execute(
            "ALTER SEQUENCE project_phase_id_seq RESTART WITH %s" % project.id
        )
        decoy = self.env["project.phase"].create({"name": "DECOY-PHASE"})
        self.env.flush_all()
        self.assertEqual(decoy.id, project.id, "precondition: the ids collide")

        project.phase_id = self.phase
        self.env.flush_all()
        self.env.cr.flush()
        project.invalidate_recordset()
        bodies = " ".join(str(message.body) for message in project.message_ids)
        self.assertNotIn("DECOY-PHASE", bodies)

    def test_a_project_template_still_posts(self):
        self.phase.mail_template_id = self.project_template
        project = self.env["project.project"].create(
            {"name": "ProjB", "privacy_visibility": "followers"}
        )
        self.env.flush_all()
        self.env.cr.flush()
        before = len(project.message_ids)
        project.phase_id = self.phase
        self.env.flush_all()
        self.env.cr.flush()
        project.invalidate_recordset()
        self.assertEqual(
            len(project.message_ids), before + 2,
            "one message for the tracking, one for the template",
        )
