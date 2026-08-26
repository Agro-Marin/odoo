from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestProjectUpdateUi(HttpCase):
    def test_01_project_tour(self) -> None:
        self.env.ref("base.group_user").implied_ids |= self.env.ref(
            "project.group_project_milestone"
        )

        self.start_tour("/odoo", "project_update_tour", login="admin")
        self.start_tour("/odoo", "project_tour", login="admin")
