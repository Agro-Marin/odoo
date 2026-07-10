from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged


class TestMergePartner(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Partner = self.env["res.partner"]
        self.Bank = self.env["res.partner.bank"]

        self.partner1 = self.Partner.create(
            {"name": "Partner 1", "email": "partner1@example.com"}
        )
        self.partner2 = self.Partner.create(
            {"name": "Partner 2", "email": "partner2@example.com"}
        )
        self.partner3 = self.Partner.create(
            {"name": "Partner 3", "email": "partner3@example.com"}
        )

        self.bank1 = self.Bank.create(
            {"acc_number": "12345", "partner_id": self.partner1.id}
        )
        self.bank2 = self.Bank.create(
            {"acc_number": "54321", "partner_id": self.partner2.id}
        )
        self.bank3 = self.Bank.create(
            {"acc_number": "12345", "partner_id": self.partner3.id}
        )  # Duplicate account number

        self.attachment1 = self.env["ir.attachment"].create(
            {
                "name": "Attachment 1",
                "res_model": "res.partner",
                "res_id": self.partner1.id,
            }
        )
        self.attachment2 = self.env["ir.attachment"].create(
            {
                "name": "Attachment 2",
                "res_model": "res.partner",
                "res_id": self.partner2.id,
            }
        )
        self.attachment_bank1 = self.env["ir.attachment"].create(
            {
                "name": "Attachment Bank 1",
                "res_model": "res.partner.bank",
                "res_id": self.bank1.id,
            }
        )
        self.attachment_bank2 = self.env["ir.attachment"].create(
            {
                "name": "Attachment Bank 2",
                "res_model": "res.partner.bank",
                "res_id": self.bank2.id,
            }
        )
        self.attachment_bank3 = self.env["ir.attachment"].create(
            {
                "name": "Attachment Bank 2",
                "res_model": "res.partner.bank",
                "res_id": self.bank3.id,
            }
        )

    def test_merge_parent_with_child_is_rejected(self):
        """Merging a contact with its own parent/child must raise.

        Regression: the guard intersected ``all_descendants - partner_ids`` back
        with ``partner_ids`` (always empty), so a parent+child merge slipped
        through and repointed the survivor onto itself (``parent_id = id``).
        """
        parent = self.Partner.create(
            {"name": "Parent Co", "email": "parent@example.com"}
        )
        child = self.Partner.create(
            {"name": "Child Co", "email": "child@example.com", "parent_id": parent.id}
        )
        wizard = self.env["base.partner.merge.automatic.wizard"].create({})
        with self.assertRaises(UserError):
            wizard._merge([parent.id, child.id])
        # Both survive unchanged; neither becomes its own parent.
        self.assertTrue(parent.exists() and child.exists())
        self.assertNotEqual(parent.parent_id, parent)
        self.assertNotEqual(child.parent_id, child)

    def test_merge_partners_without_bank_accounts(self):
        partner4 = self.Partner.create(
            {"name": "Partner 4", "email": "partner4@example.com"}
        )
        partner5 = self.Partner.create(
            {"name": "Partner 5", "email": "partner5@example.com"}
        )
        wizard = self.env["base.partner.merge.automatic.wizard"].create({})
        wizard._merge([partner4.id, partner5.id], partner4)
        self.assertFalse(
            partner5.exists(), "Source partner should be deleted after merge"
        )
        self.assertTrue(
            partner4.exists(), "Destination partner should exist after merge"
        )

    def test_merge_partners_with_unique_bank_accounts(self):
        wizard = self.env["base.partner.merge.automatic.wizard"].create({})
        wizard._merge([self.partner1.id, self.partner2.id], self.partner1)

        self.assertFalse(
            self.partner2.exists(),
            "Source partner should be deleted after merge",
        )
        self.assertTrue(
            self.partner1.exists(),
            "Destination partner should exist after merge",
        )
        self.assertEqual(
            self.bank1.partner_id,
            self.partner1,
            "Bank account should belong to destination partner",
        )
        self.assertEqual(
            self.bank2.partner_id,
            self.partner1,
            "Bank account should be reassigned to destination partner",
        )

    def test_merge_partners_with_duplicate_bank_accounts(self):
        wizard = self.env["base.partner.merge.automatic.wizard"].create({})
        src_partners = self.partner1 + self.partner3
        wizard._merge((src_partners + self.partner2).ids, self.partner2)

        self.assertFalse(
            src_partners.exists(),
            "Source partners should be deleted after merge",
        )
        self.assertTrue(
            self.partner2.exists(),
            "Destination partner should exist after merge",
        )
        self.assertRecordValues(
            self.partner2.bank_ids,
            [
                {"acc_number": "12345"},
                {"acc_number": "54321"},
            ],
        )
        self.assertEqual(
            self.attachment_bank1.res_id,
            self.bank1.id,
            "Bank attachment should remain linked to the correct bank account",
        )
        self.assertEqual(
            self.attachment_bank3.res_id,
            self.bank1.id,
            "Bank attachment should be reassigned to the correct bank account",
        )

    def test_merge_partners_with_duplicate_bank_accounts_with_destination(self):
        wizard = self.env["base.partner.merge.automatic.wizard"].create({})
        wizard._merge([self.partner1.id, self.partner3.id], self.partner1)

        self.assertFalse(
            self.partner3.exists(),
            "Source partner should be deleted after merge",
        )
        self.assertTrue(
            self.partner1.exists(),
            "Destination partner should exist after merge",
        )
        self.assertEqual(
            len(self.partner1.bank_ids),
            1,
            "There should be a single bank account after merge",
        )
        self.assertIn(
            self.bank1,
            self.partner1.bank_ids,
            "The original bank account of the destination partner should remain",
        )
        self.assertFalse(
            self.bank3.exists(),
            "The duplicate bank account should have been deleted.",
        )

    def test_merge_partners_with_references(self):
        wizard = self.env["base.partner.merge.automatic.wizard"].create({})
        wizard._merge([self.partner1.id, self.partner2.id], self.partner1)

        self.assertFalse(
            self.partner2.exists(),
            "Source partner should be deleted after merge",
        )
        self.assertTrue(
            self.partner1.exists(),
            "Destination partner should exist after merge",
        )
        self.assertEqual(
            self.attachment1.res_id,
            self.partner1.id,
            "Attachment should be linked to the destination partner",
        )
        self.assertEqual(
            self.attachment2.res_id,
            self.partner1.id,
            "Attachment should be reassigned to the destination partner",
        )

    def test_merge_partners_with_peon_user(self):
        """Test merging partners with a user having the bare minimum access rights"""
        self.env["ir.model.access"].create(
            {
                "name": "peon.access.merge.wizard",
                "group_id": self.env.ref("base.group_user").id,
                "model_id": self.env.ref(
                    "base.model_base_partner_merge_automatic_wizard"
                ).id,
                "perm_read": 1,
                "perm_write": 1,
                "perm_create": 1,
            }
        )
        self.env["ir.model.access"].create(
            {
                "name": "peon.access.merge.wizard.line",
                "group_id": self.env.ref("base.group_user").id,
                "model_id": self.env.ref("base.model_base_partner_merge_line").id,
                "perm_read": 1,
                "perm_write": 1,
                "perm_create": 1,
            }
        )
        partner_peon = self.env["res.partner"].create(
            {
                "name": "Peon",
                "email": "mark.peon@example.com",
            }
        )
        user_peon = self.env["res.users"].create(
            {
                "login": "peon",
                "password": "peon",
                "partner_id": partner_peon.id,
                "group_ids": [Command.set([self.env.ref("base.group_user").id])],
            }
        )

        # internal user doesn't have the right to write on res.partner.bank
        with self.assertRaises(AccessError):
            self.bank1.with_user(user_peon).partner_id = self.partner2

        wizard = (
            self.env["base.partner.merge.automatic.wizard"]
            .with_user(user_peon)
            .create({})
        )
        src_partners = self.partner1 + self.partner3
        wizard._merge(
            (src_partners + self.partner2).ids,
            self.partner2,
            extra_checks=False,
        )

        self.assertFalse(
            src_partners.exists(),
            "Source partners should be deleted after merge",
        )
        self.assertTrue(
            self.partner2.exists(),
            "Destination partner should exist after merge",
        )
        self.assertRecordValues(
            self.partner2.bank_ids,
            [
                {"acc_number": "12345"},
                {"acc_number": "54321"},
            ],
        )
        self.assertEqual(
            self.attachment_bank1.res_id,
            self.bank1.id,
            "Bank attachment should remain linked to the correct bank account",
        )
        self.assertEqual(
            self.attachment_bank3.res_id,
            self.bank1.id,
            "Bank attachment should be reassigned to the correct bank account",
        )

    def test_merge_aligns_user_company_to_destination(self):
        """Merge re-homes a linked user to the destination partner's company.

        res.partner requires its company_id to match its users' company. BPM-L03's
        proposed "preserve the user's own default" is NOT viable: it would leave
        partner and user inconsistent and abort the merge.
        """
        Company = self.env["res.company"]
        company_a, company_b = Company.create(
            [{"name": "Merge A"}, {"name": "Merge B"}]
        )
        src = self.Partner.create(
            {"name": "merge src", "email": "m@example.com", "company_id": company_a.id}
        )
        dst = self.Partner.create(
            {"name": "merge dst", "email": "m@example.com", "company_id": company_b.id}
        )
        user = self.env["res.users"].create(
            {
                "login": "merge_company_user",
                "partner_id": src.id,
                "company_id": company_a.id,
                "company_ids": [Command.set([company_a.id, company_b.id])],
            }
        )
        self.env["base.partner.merge.automatic.wizard"].create({})._merge(
            [src.id, dst.id], dst
        )
        self.assertEqual(user.company_id, company_b)
        self.assertIn(company_b, user.company_ids)


@tagged("post_install", "-at_install")
class TestMergePartnerForeignKeyClash(TransactionCase):
    """BPM-L06: on a multi-column UNIQUE/CHECK clash, the FK-update helper must
    repoint the non-clashing source rows and drop only the offending row, not
    blanket-delete every source row.

    res_partner_bank's ``unique(sanitized_acc_number, partner_id)`` constraint
    lets a source bank row whose number already exists on dst drive the savepoint
    ``else`` branch of ``_update_foreign_keys_generic``. The helper is called
    directly, not via ``_merge``, because ``_merge`` re-points bank accounts in
    ``_merge_bank_accounts`` before the generic FK pass runs.
    """

    def test_clashing_row_dropped_non_clashing_repointed(self):
        Partner = self.env["res.partner"]
        Bank = self.env["res.partner.bank"]
        dst = Partner.create({"name": "fk dst", "email": "fk@example.com"})
        src_clash = Partner.create({"name": "fk src clash", "email": "fk@example.com"})
        src_keep = Partner.create({"name": "fk src keep", "email": "fk@example.com"})

        # dst already owns "CLASH"; re-pointing the clashing source's identical
        # number to dst collides on (sanitized_acc_number, partner_id). The other
        # source's number is unique and must survive the re-point.
        Bank.create({"acc_number": "CLASH", "partner_id": dst.id})
        bank_clash = Bank.create({"acc_number": "CLASH", "partner_id": src_clash.id})
        bank_keep = Bank.create({"acc_number": "UNIQUE-B", "partner_id": src_keep.id})

        wizard = self.env["base.partner.merge.automatic.wizard"].create({})
        wizard._update_foreign_keys_generic("res.partner", src_clash + src_keep, dst)
        # The helper works in raw SQL; drop stale ORM cache before re-reading.
        self.env.invalidate_all()

        self.assertTrue(
            bank_keep.exists(),
            "the non-clashing source bank row must survive the re-point",
        )
        self.assertEqual(
            bank_keep.partner_id,
            dst,
            "the non-clashing source bank row must be repointed to dst, not deleted",
        )
        self.assertFalse(
            bank_clash.exists(),
            "only the clashing source bank row must be dropped",
        )


@tagged("post_install", "-at_install")
class TestMergePartnerCompanyDependent(TransactionCase):
    """BPM-P1: company-dependent references on merged partners must still resolve
    after the EXISTS row-filter optimisation of the company-dependent jsonb rewrite.

    The jsonb-m2o path (``many2one_company_dependents[dst._name]``) can't be tested
    directly: no base model declares a ``company_dependent=True`` Many2one at
    res.partner, and adding a throwaway jsonb-backed model would require runtime
    table creation plus registry teardown with no precedent in the suite. This
    exercises the adjacent path via the real ``res.partner.barcode`` field instead.
    """

    def test_company_dependent_reference_resolves_after_merge(self):
        Company = self.env["res.company"]
        company_a, company_b = Company.create(
            [{"name": "BPM-P1 A"}, {"name": "BPM-P1 B"}]
        )
        Partner = self.env["res.partner"]
        src = Partner.create({"name": "cd src", "email": "cd@example.com"})
        dst = Partner.create({"name": "cd dst", "email": "cd@example.com"})
        # An unrelated partner whose per-company value must stay untouched.
        bystander = Partner.create({"name": "cd bystander"})
        bystander.with_company(company_a).barcode = "BYSTANDER-A"

        # The source carries a per-company barcode; the destination has none in
        # company_a, so the merge must surface the source's value on dst.
        src.with_company(company_a).barcode = "SRC-A"
        src.with_company(company_b).barcode = "SRC-B"

        self.env["base.partner.merge.automatic.wizard"].create({})._merge(
            [src.id, dst.id], dst
        )
        self.env.invalidate_all()

        self.assertFalse(src.exists(), "source partner must be deleted after merge")
        self.assertEqual(
            dst.with_company(company_a).barcode,
            "SRC-A",
            "the source's per-company value must be carried onto the destination",
        )
        self.assertEqual(
            dst.with_company(company_b).barcode,
            "SRC-B",
            "each company slot must resolve independently after the merge",
        )
        self.assertEqual(
            bystander.with_company(company_a).barcode,
            "BYSTANDER-A",
            "an unrelated partner's per-company value must be left untouched",
        )
