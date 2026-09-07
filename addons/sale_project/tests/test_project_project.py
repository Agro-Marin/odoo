from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


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

    def test_reinvoiced_order_selectable_across_the_commercial_entity(self):
        """The picker offers the orders of the whole commercial entity, not one contact."""
        company_partner, other_company = self.env["res.partner"].create(
            [
                {"name": "Agrozihua", "is_company": True},
                {"name": "Unrelated company", "is_company": True},
            ]
        )
        contact = self.env["res.partner"].create(
            {
                "name": "Agrozihua, Villa Victoria",
                "parent_id": company_partner.id,
                "type": "delivery",
            }
        )
        order_of_contact, order_of_company, order_of_other = self.env[
            "sale.order"
        ].create(
            [
                {"partner_id": contact.id},
                {"partner_id": company_partner.id},
                {"partner_id": other_company.id},
            ]
        )
        project = self.env["project.project"].create(
            {
                "name": "Mur en beton",
                "allow_billable": True,
                "partner_id": company_partner.id,
            }
        )

        # The web client evaluates the field's own domain against the record.
        domain = safe_eval(
            project._fields["reinvoiced_sale_order_id"].domain,
            {"partner_id": project.partner_id.id},
        )
        selectable = self.env["sale.order"].search(domain)

        self.assertIn(
            order_of_contact,
            selectable,
            "An order booked on a contact of the customer must be selectable.",
        )
        self.assertIn(
            order_of_company,
            selectable,
            "The customer's own orders must stay selectable.",
        )
        self.assertNotIn(
            order_of_other,
            selectable,
            "Another company's orders must not leak into the picker.",
        )
