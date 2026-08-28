"""One ``account.tax.group`` record can serve several companies.

The group used to carry a ``company_id`` many2one, so two companies wanting the
same grouping ("VAT 16%", "IEPS") held two rows that nothing kept in step. It
now carries ``company_ids``, matching ``account.account``.

What these tests pin is the part a schema change alone does not give you: that
the record rule and ``_check_company_domain`` agree with the new field, that a
tax of either member company can point at the shared group, and that a company
outside the set is refused. The last one is the discriminating case -- a
membership check that accepts everyone would pass every other assertion here.
"""

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestTaxGroupMultiCompany(BaseTaxCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env["res.company"].create(
            {"name": "base_tax group company B", "country_id": cls.country.id}
        )
        cls.company_c = cls.env["res.company"].create(
            {"name": "base_tax group company C", "country_id": cls.country.id}
        )
        cls.shared_group = cls.env["account.tax.group"].create(
            {
                "name": "base_tax shared group",
                "company_ids": [Command.set((cls.company + cls.company_b).ids)],
                "country_id": cls.country.id,
            }
        )
        # C needs a group of its own, or the picker finds nothing for it and the
        # required `tax_group_id` fails on a NOT NULL rather than on membership --
        # which would make the outsider assertion pass for the wrong reason.
        cls.own_group_c = cls.env["account.tax.group"].create(
            {
                "name": "base_tax company C group",
                "company_ids": [Command.set(cls.company_c.ids)],
                "country_id": cls.country.id,
            }
        )

    def _tax_in(self, company, tax_group):
        return (
            self.env["account.tax"]
            .with_company(company)
            .create(
                {
                    "name": f"shared-group tax {company.id}",
                    "type_tax_use": "sale",
                    "amount_type": "percent",
                    "amount": 16,
                    "country_id": self.country.id,
                    "tax_group_id": tax_group.id,
                }
            )
        )

    def _tax_without_group(self, company):
        # `tax_group_id` omitted on purpose: it is `precompute=True`, so leaving
        # it out is what runs `_compute_tax_group_id`. Passing False suppresses
        # the compute and dies on the required constraint instead.
        return (
            self.env["account.tax"]
            .with_company(company)
            .create(
                {
                    "name": f"picked-group tax {company.id}",
                    "type_tax_use": "sale",
                    "amount_type": "percent",
                    "amount": 16,
                    "country_id": self.country.id,
                }
            )
        )

    def test_group_belongs_to_several_companies(self):
        self.assertEqual(self.shared_group.company_ids, self.company + self.company_b)

    def test_either_member_company_may_use_the_group(self):
        for company in (self.company, self.company_b):
            tax = self._tax_in(company, self.shared_group)
            self.assertEqual(tax.company_ids, company)
            self.assertEqual(tax.tax_group_id, self.shared_group)

    def test_the_group_picker_respects_membership(self):
        # `tax_group_id` carries no `check_company=True`, so nothing *rejects* a
        # tax pointing at a group that does not cover its company -- true before
        # this change as much as after, and out of scope here. What the model
        # does promise is that the automatic pick covers the tax's company, and
        # that is what this asserts, in both directions.
        picked_for_member = self._tax_without_group(self.company)
        self.assertIn(
            self.company,
            picked_for_member.tax_group_id.company_ids,
            "the picked group must cover the tax's own company",
        )

        picked_for_outsider = self._tax_without_group(self.company_c)
        self.assertNotEqual(
            picked_for_outsider.tax_group_id,
            self.shared_group,
            "a company outside the membership must not be handed the shared group",
        )
        self.assertEqual(picked_for_outsider.tax_group_id, self.own_group_c)

    def test_check_company_domain_matches_membership(self):
        Group = self.env["account.tax.group"]
        for company, expected in (
            (self.company, True),
            (self.company_b, True),
            (self.company_c, False),
        ):
            found = Group.search(
                [
                    *Group._check_company_domain(company),
                    ("id", "=", self.shared_group.id),
                ]
            )
            self.assertEqual(
                bool(found),
                expected,
                f"_check_company_domain disagrees with membership for {company.name}",
            )

    def test_record_rule_hides_the_group_from_a_non_member(self):
        Group = self.env["account.tax.group"]
        reader = self.env["res.users"].create(
            {
                "name": "base_tax group reader",
                "login": "base_tax_group_reader",
                "company_id": self.company_c.id,
                "company_ids": [Command.set(self.company_c.ids)],
                "group_ids": [Command.set(self.env.ref("base.group_user").ids)],
            }
        )
        visible = Group.with_user(reader).search([("id", "=", self.shared_group.id)])
        self.assertFalse(
            visible,
            "the multi-company rule must read company_ids, not a stale company_id",
        )

    def test_a_group_must_belong_to_at_least_one_company(self):
        with self.assertRaises(ValidationError):
            self.env["account.tax.group"].create(
                {
                    "name": "companyless group",
                    "company_ids": [Command.clear()],
                    "country_id": self.country.id,
                }
            )
