from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged


class TestCompany(TransactionCase):
    def test_check_active(self):
        """Tests the ability to archive a company whether or not it still has active users.
        Tests an archived user in an archived company cannot be unarchived
        without changing its company to an active company."""
        company = self.env["res.company"].create({"name": "foo"})
        user = self.env["res.users"].create(
            {
                "name": "foo",
                "login": "foo",
                "company_id": company.id,
                "company_ids": company.ids,
            }
        )

        # The company cannot be archived because it still has active users
        with self.assertRaisesRegex(
            ValidationError, "The company foo cannot be archived"
        ):
            company.action_archive()

        # The company can be archived because it has no active users
        user.action_archive()
        company.action_archive()

        # The user cannot be unarchived because it's default company is archived
        with self.assertRaisesRegex(
            ValidationError, "Company foo is not in the allowed companies"
        ):
            user.action_unarchive()

        # The user can be unarchived once we set another, active, company
        main_company = self.env.ref("base.main_company")
        user.write(
            {
                "company_id": main_company.id,
                "company_ids": main_company.ids,
            }
        )
        user.action_unarchive()

    def test_logo_check(self):
        """Ensure uses_default_logo is properly (re-)computed."""
        company = self.env["res.company"].create({"name": "foo"})

        self.assertTrue(company.logo, "Should have a default logo")
        self.assertTrue(company.uses_default_logo)
        company.partner_id.image_1920 = False
        # No logo means we fall back to another default logo for the website route -> uses_default
        self.assertTrue(company.uses_default_logo)
        company.partner_id.image_1920 = (
            "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
        )
        self.assertFalse(company.uses_default_logo)

    def test_create_branch_with_default_parent_id(self):
        branch = (
            self.env["res.company"]
            .with_context(default_parent_id=self.env.company.id)
            .create({"name": "Branch Company"})
        )
        self.assertFalse(branch.partner_id.parent_id)


@tagged("post_install", "-at_install")
class TestCompanyPublicUser(TransactionCase):
    """Regression coverage for RC-L3: res.company._get_public_user() must probe
    the company's public user by its deterministic per-company login before
    copying base.public_user (res_company.py:_get_public_user), so it does not
    raise on the global login-uniqueness constraint when an existing public user
    is missing from base.group_public.
    """

    def test_get_public_user_creates_one_per_company(self):
        """First call copies base.public_user with the per-company login."""
        company = self.env["res.company"].create({"name": "Public Co"})
        public_user = company._get_public_user()
        self.assertTrue(public_user)
        self.assertEqual(public_user.company_id, company)
        self.assertEqual(public_user.login, f"public-user@company-{company.id}.com")

    def test_get_public_user_is_idempotent(self):
        """A second call returns the same record, not a duplicate."""
        company = self.env["res.company"].create({"name": "Public Co 2"})
        first = company._get_public_user()
        second = company._get_public_user()
        self.assertEqual(first, second)

    def test_get_public_user_found_without_group_public_membership(self):
        """RC-L3: an existing public user whose base.group_public membership was
        removed out of band is still found by login and returned, instead of the
        copy raising on the global login-uniqueness constraint."""
        company = self.env["res.company"].create({"name": "Public Co 3"})
        public_user = company._get_public_user()
        # Simulate a stale / half-rolled-back state: the public user for this
        # company exists but is no longer a member of base.group_public, so the
        # old group-membership probe would miss it and the deterministic-login
        # copy would collide on the global UNIQUE(login) constraint.
        public_group = self.env.ref("base.group_public")
        public_user.sudo().write({"group_ids": [Command.unlink(public_group.id)]})
        self.assertNotIn(public_user, public_group.sudo().all_user_ids)

        # Must return the existing record (by login probe), not raise / duplicate.
        again = company._get_public_user()
        self.assertEqual(
            again,
            public_user,
            "The public user must be found by its per-company login even when "
            "it is not a member of base.group_public (RC-L3).",
        )
