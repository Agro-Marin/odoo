"""`hr.skill.type.display_name` appends a badge when `is_certification`."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSkillTypeDependsCompleteness(TransactionCase):
    def test_display_name_follows_is_certification(self):
        skill_type = self.env["hr.skill.type"].create({"name": "Depends probe"})
        self.assertDependsComplete(
            skill_type,
            computed_fields=["display_name"],
            probe_fields=["name", "is_certification"],
        )
