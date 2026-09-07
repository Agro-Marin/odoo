from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("-at_install", "post_install")
class TestProjectProject(TransactionCase):
    def test_projects_to_make_billable(self):
        """Test the projects fetched in the post init are the ones expected"""
        Project = self.env["project.project"]
        Task = self.env["project.task"]
        partner = self.env["res.partner"].create({"name": "Mur en béton"})
        project1, project2, project3 = Project.create(
            [
                {
                    "name": "Project with partner",
                    "partner_id": partner.id,
                    "allow_billable": False,
                },
                {"name": "Project without partner", "allow_billable": False},
                {"name": "Project without partner 2", "allow_billable": False},
            ]
        )
        Task.create(
            [
                {
                    "name": "Task with partner in project 2",
                    "project_id": project2.id,
                    "partner_id": partner.id,
                },
                {
                    "name": "Task without partner in project 2",
                    "project_id": project2.id,
                },
                {
                    "name": "Task without partner in project 3",
                    "project_id": project3.id,
                },
            ]
        )
        projects_to_make_billable = Project.search(
            Project._get_domain_projects_to_make_billable()
        )
        (non_billable_projects,) = Task._read_group(
            Task._get_domain_projects_to_make_billable(
                [("project_id", "not in", projects_to_make_billable.ids)]
            ),
            [],
            ["project_id:recordset"],
        )[0]
        projects_to_make_billable += non_billable_projects
        self.assertEqual(projects_to_make_billable, project1 + project2)

    def test_sale_order_actions_are_named_after_the_menu(self):
        """The two sales entries of the dashboard name the menu, like their siblings."""
        project = self.env["project.project"].create(
            {"name": "Mur en beton", "allow_billable": True}
        )
        self.assertEqual(
            project.action_view_project_invoices()["name"],
            "Invoices",
            "Reference point: the sibling entries have always named the menu only.",
        )
        self.assertEqual(
            project.action_view_sols()["name"],
            "Sales Order Items",
            "The Sales Order Items entry must not prefix the project name.",
        )
        # `_get_action_dict_by_xml_id` already carries the action's own
        # display_name, so the entry is right when it is left alone.
        self.assertEqual(
            project.action_view_sos()["display_name"],
            "Sales Orders",
            "The Sales Orders entry must not override its own name with the project's.",
        )
