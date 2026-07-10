from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.res_company import ResCompany


class TestCompany(TransactionCase):
    def test_check_active(self):
        """A company can be archived only with no active users, and an archived
        user in an archived company cannot be unarchived without first moving it
        to an active company."""
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
        with self.assertRaisesRegex(ValidationError, r"cannot be archived[\s\S]*foo"):
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

    def test_check_active_aggregates_all_offending_companies(self):
        """Archiving several companies with active users reports ALL offenders
        in a single ValidationError instead of only the first one."""
        company_a, company_b = self.env["res.company"].create(
            [{"name": "arch co A"}, {"name": "arch co B"}]
        )
        for i, company in enumerate((company_a, company_b)):
            self.env["res.users"].create(
                {
                    "name": f"arch user {i}",
                    "login": f"arch_user_{i}",
                    "company_id": company.id,
                    "company_ids": company.ids,
                }
            )
        with self.assertRaises(ValidationError) as capture:
            (company_a + company_b).action_archive()
        message = str(capture.exception)
        self.assertIn("arch co A", message)
        self.assertIn("arch co B", message)

    def test_logo_check(self):
        """Ensure uses_default_logo is properly (re-)computed."""
        company = self.env["res.company"].create({"name": "foo"})

        self.assertTrue(company.logo, "Should have a default logo")
        self.assertTrue(company.uses_default_logo)
        company.partner_id.image_1920 = False
        # No logo falls back to a default logo, so uses_default_logo stays True.
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

    def test_color_follows_root_partner_color(self):
        """Branch color must be recomputed when the root partner color changes."""
        root = self.env["res.company"].create({"name": "color root"})
        branch = self.env["res.company"].create(
            {"name": "color branch", "parent_id": root.id}
        )
        # Prime both caches before changing the root partner's color.
        self.assertEqual(root.color, branch.color)
        # Two successive writes: at most one value can coincide with the
        # ``root.id % 12`` fallback, so a stale cache cannot pass both.
        for color in (5, 7):
            root.partner_id.color = color
            self.assertEqual(root.color, color)
            self.assertEqual(
                branch.color,
                color,
                "Cached branch color must not go stale when the root partner's"
                " color changes",
            )

    def test_company_partner_ids_cache_invalidation(self):
        """Changing a company's partner_id must invalidate the ormcached
        _get_company_partner_ids (feeds the own-company bank account guard)."""
        Company = self.env["res.company"]
        company = Company.create({"name": "cache co"})
        self.assertIn(company.partner_id.id, Company._get_company_partner_ids())

        new_partner = self.env["res.partner"].create(
            {"name": "new company partner", "is_company": True}
        )
        company.write({"partner_id": new_partner.id})
        self.assertIn(
            new_partner.id,
            Company._get_company_partner_ids(),
            "partner_id writes must invalidate the company partner ids cache",
        )

    def test_compute_address_calls_update_hook(self):
        """_compute_address must resolve values via the overridable
        _get_company_address_update() extension point."""
        company = self.env["res.company"].create({"name": "hook co"})
        company.partner_id.write({"street": "1 Hook St", "city": "Hookville"})
        original = ResCompany._get_company_address_update
        seen_partners = []

        def _spy(self, partner):
            seen_partners.append(partner)
            return original(self, partner)

        with patch.object(ResCompany, "_get_company_address_update", _spy):
            company.invalidate_recordset(["street", "city"])
            self.assertEqual(company.street, "1 Hook St")
            self.assertEqual(company.city, "Hookville")
        self.assertTrue(
            seen_partners, "_compute_address must call _get_company_address_update"
        )


@tagged("post_install", "-at_install")
class TestCompanyPublicUser(TransactionCase):
    """RC-L3: res.company._get_public_user() probes the public user by its
    per-company login before copying base.public_user, so it does not raise on
    the global login-uniqueness constraint when an existing public user is
    missing from base.group_public.
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
        # Stale state: the public user exists but is no longer a member of
        # base.group_public, so the old group-membership probe would miss it and
        # the login copy would collide on the global UNIQUE(login) constraint.
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
