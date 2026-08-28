import psycopg

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestAnalyticPlanOperations(TransactionCase):
    def test_delete_plan(self):
        plan = self.env["account.analytic.plan"].create({"name": "Test Plan"})
        column = plan._column_name()

        # the column exists
        self.env.cr.execute(f"SELECT {column} FROM account_analytic_line LIMIT 1")

        plan.unlink()
        with self.assertRaises(psycopg.errors.UndefinedColumn), mute_logger("odoo.db"):
            # column has been deleted
            self.env.cr.execute(f"SELECT {column} FROM account_analytic_line LIMIT 1")

    def test_delete_subplan(self):
        parent = self.env["account.analytic.plan"].create({"name": "Parent Plan"})
        plan = self.env["account.analytic.plan"].create(
            {"name": "Test Plan", "parent_id": parent.id}
        )
        other_plan = self.env["account.analytic.plan"].create(
            {"name": "Other Plan", "parent_id": parent.id}
        )
        self.assertFalse(plan._get_plan_column("account.analytic.line"))
        related_field = plan._get_related_field("account.analytic.line")
        self.assertTrue(related_field.exists())
        other_plan.unlink()
        self.assertTrue(related_field.exists())
        plan.unlink()
        self.assertFalse(related_field.exists())

    def test_rename_plan(self):
        plan = self.env["account.analytic.plan"].create({"name": "Test Plan"})
        column = plan._get_plan_column("account.analytic.line")
        plan.name = "New name"
        self.assertEqual(column.field_description, "New name")

    def test_promote_subplan(self):
        parent = self.env["account.analytic.plan"].create({"name": "Parent Plan"})
        plan = self.env["account.analytic.plan"].create(
            {"name": "Test Plan", "parent_id": parent.id}
        )
        self.assertFalse(plan._get_plan_column("account.analytic.line"))
        self.assertTrue(plan._get_related_field("account.analytic.line"))
        plan.parent_id = False
        self.assertTrue(plan._get_plan_column("account.analytic.line"))
        self.assertFalse(plan._get_related_field("account.analytic.line"))

    def test_demote_plan(self):
        parent = self.env["account.analytic.plan"].create({"name": "Parent Plan"})
        plan = self.env["account.analytic.plan"].create({"name": "Test Plan"})
        self.assertTrue(plan._get_plan_column("account.analytic.line"))
        self.assertFalse(plan._get_related_field("account.analytic.line"))
        plan.parent_id = parent
        self.assertFalse(plan._get_plan_column("account.analytic.line"))
        self.assertTrue(plan._get_related_field("account.analytic.line"))

    def test_project_plan_cannot_be_reparented(self):
        # `_onchange_parent_id` only guards the form UI; a direct write (RPC,
        # scripts, other modules) must be blocked too, since the "Project"
        # plan referenced by `analytic.project_plan` is assumed to always be
        # a root plan (see the comment in `data/analytic_data.xml`).
        project_plan, __ = self.env["account.analytic.plan"]._get_all_plans()
        other_plan = self.env["account.analytic.plan"].create({"name": "Other Plan"})
        with self.assertRaises(ValidationError):
            project_plan.parent_id = other_plan.id

    def test_delete_plan_with_view(self):
        plan = self.env["account.analytic.plan"].create({"name": "Test Plan"})
        column = plan._column_name()

        self.env["ir.ui.view"].create(
            {
                "name": "Manual view",
                "model": "account.analytic.line",
                "type": "search",
                "arch": f'<search><field name="{column}"/></search>',
            }
        )

        # can't delete a plan still used in a view
        with self.assertRaisesRegex(UserError, "still present in views"):
            plan.unlink()

    def test_validate_deleted_account(self):
        plan, mandatory_plan = self.env["account.analytic.plan"].create(
            [
                {
                    "name": "Test Plan",
                },
                {
                    "name": "Mandatory Plan",
                    "default_applicability": "mandatory",
                },
            ]
        )
        test_account, mandatory_account = self.env["account.analytic.account"].create(
            [
                {
                    "name": "Test Account",
                    "code": "TAC",
                    "plan_id": plan.id,
                },
                {
                    "name": "Mandatory Account",
                    "code": "manda",
                    "plan_id": mandatory_plan.id,
                },
            ]
        )
        distribution_model = (
            self.env["account.analytic.distribution.model"]
            .create({"analytic_distribution": {f"{test_account.id}": 100}})
            .with_context(validate_analytic=True)
        )

        # the configuration makes it raise an error
        with self.assertRaisesRegex(UserError, r"require a 100% analytic distribution"):
            distribution_model._validate_distribution()

        # once it is fixed, the error is not raised anymore
        distribution_model.analytic_distribution = {
            f"{test_account.id},{mandatory_account.id}": 100
        }
        distribution_model._validate_distribution()

        # even by keeping a deleted account, the validation still works
        test_account.unlink()
        plan.unlink()
        distribution_model._validate_distribution()

    def test_validate_company_plans(self):
        company_2 = self.env["res.company"].create(
            {
                "name": "company_2",
            }
        )
        plan, other_plan = self.env["account.analytic.plan"].create(
            [
                {
                    "name": "Plan",
                    "default_applicability": "optional",
                },
                {
                    "name": "Other Plan",
                },
            ]
        )
        applicability = self.env["account.analytic.applicability"].create(
            {
                "business_domain": "general",
                "analytic_plan_id": plan.id,
                "applicability": "mandatory",
                "company_id": company_2.id,
            }
        )
        self.env["account.analytic.account"].create(
            [
                {
                    "name": "Mandatory Account",
                    "code": "manda",
                    "plan_id": plan.id,
                }
            ]
        )
        # The distribution has to point somewhere now that it cannot be empty, and it
        # must point *outside* `plan`: a distribution naming the mandatory plan's own
        # account would satisfy the applicability under test and the assertions below
        # would stop meaning anything.
        other_account = self.env["account.analytic.account"].create(
            [
                {
                    "name": "Other Account",
                    "code": "other",
                    "plan_id": other_plan.id,
                }
            ]
        )
        distribution_model = (
            self.env["account.analytic.distribution.model"]
            .create({"analytic_distribution": {f"{other_account.id}": 100}})
            .with_context(validate_analytic=True)
        )

        # mandatory applicability is only in company_2, should not raise for company_1
        distribution_model._validate_distribution(
            business_domain="general", company_id=self.env.company.id
        )

        applicability.company_id = False
        # It should apply for all companies now
        with self.assertRaisesRegex(UserError, r"require a 100% analytic distribution"):
            distribution_model._validate_distribution(
                business_domain="general", company_id=self.env.company.id
            )
        with self.assertRaisesRegex(UserError, r"require a 100% analytic distribution"):
            distribution_model._validate_distribution(business_domain="general")

    def test_distribution_model_requires_a_distribution(self):
        """A distribution model exists only to carry a distribution, so it must have one."""
        ADM = self.env["account.analytic.distribution.model"]
        partner = self.env["res.partner"].create({"name": "Partner"})

        with self.assertRaises(psycopg.errors.NotNullViolation), mute_logger("odoo.db"):
            ADM.create({"partner_id": partner.id})

    def test_distribution_model_rejects_an_empty_distribution(self):
        """An empty mapping is not a distribution either.

        `Json.convert_to_cache` maps every falsy value to `None`, so `{}` reaches the
        column as NULL and the same constraint catches it. Pinned because a reader would
        reasonably expect `required` to stop only `False`.
        """
        ADM = self.env["account.analytic.distribution.model"]

        with self.assertRaises(psycopg.errors.NotNullViolation), mute_logger("odoo.db"):
            ADM.create({"analytic_distribution": {}})
