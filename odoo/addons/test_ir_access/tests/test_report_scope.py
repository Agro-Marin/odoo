from odoo import Command
from odoo.tests import TransactionCase, new_test_user

REPORT = "test_ir_access.reached_report"


class TestScopedGrantOnAReport(TransactionCase):
    # a report read from a query belongs to companies like any model, so a
    # grant held in some companies reaches only their rows of it (and the
    # company-less ones), wherever else the user may work

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Report B"})
        group = cls.env["res.groups"].create({"name": "Reads the report"})
        cls.env["ir.access"].create(
            {
                "name": "report: every row",
                "model_id": cls.env["ir.model"]._get_id(REPORT),
                "group_id": group.id,
                "kind": "permission",
                "operation": "r",
            }
        )
        cls.user = new_test_user(
            cls.env,
            login="report_scope",
            groups="base.group_user",
            company_ids=[Command.set((cls.company_a | cls.company_b).ids)],
        )
        cls.env["res.users.grant"].create(
            {
                "user_id": cls.user.id,
                "group_id": group.id,
                "company_ids": [Command.set(cls.company_a.ids)],
            }
        )
        Reached = cls.env["test_ir_access.reached"]
        cls.names = {"in A", "in B", "in none"}
        Reached.create(
            [
                {"name": "in A", "company_id": cls.company_a.id},
                {"name": "in B", "company_id": cls.company_b.id},
                {"name": "in none", "company_id": False},
            ]
        )
        cls.env.flush_all()

    def test_a_grant_held_in_one_company_reads_its_rows_of_the_report(self):
        env = self.env(
            user=self.user,
            context={"allowed_company_ids": (self.company_a | self.company_b).ids},
        )
        self.assertEqual(env[REPORT]._access_company_anchor(), "company_id")
        rows = env[REPORT].search([("name", "in", list(self.names))])
        self.assertEqual(set(rows.mapped("name")), {"in A", "in none"})
