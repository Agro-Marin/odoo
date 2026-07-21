# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResPartnerBankTrust(TransactionCase):
    """Tests for the account extension of res.partner.bank."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.RPB = cls.env["res.partner.bank"]
        cls.be = cls.env.ref("base.be")
        cls.fr = cls.env.ref("base.fr")
        cls.partner_be = cls.env["res.partner"].create(
            {"name": "BE Vendor", "country_id": cls.be.id, "is_company": True}
        )
        cls.partner_fr = cls.env["res.partner"].create(
            {"name": "FR Vendor", "country_id": cls.fr.id, "is_company": True}
        )
        # A user allowed to manage bank accounts but WITHOUT the trust group.
        cls.clerk = cls.env["res.users"].create(
            {
                "name": "Billing Clerk",
                "login": "clerk_trust_test",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("account.group_account_invoice").id,
                        ],
                    )
                ],
            }
        )

    # -- money-transfer detection (institution codes are Belgian) --------------

    def test_money_transfer_belgian_account_detected(self):
        """A Belgian IBAN with a money-transfer bank code (positions 5-7) is flagged."""
        acc = self.RPB.create(
            {"acc_number": "BE40967000000063", "partner_id": self.partner_be.id}
        )
        self.assertEqual(acc.money_transfer_service, "Wise")
        self.assertEqual(acc._get_money_transfer_service(), "Wise")
        # The warning flag additionally requires IBAN detection (base_iban).
        if acc.acc_type == "iban":
            self.assertTrue(acc.has_money_transfer_warning)

    def test_money_transfer_foreign_account_not_false_positive(self):
        """A French IBAN with bank code "967" is not mislabelled as "Wise"."""
        acc = self.RPB.create(
            {
                "acc_number": "FR7296700000000000000000000",
                "partner_id": self.partner_fr.id,
            }
        )
        self.assertEqual(acc.sanitized_acc_number[4:7], "967")
        self.assertFalse(acc.money_transfer_service)
        self.assertIsNone(acc._get_money_transfer_service())
        if acc.acc_type == "iban":
            self.assertFalse(acc.has_money_transfer_warning)

    def test_money_transfer_service_independent_of_trust(self):
        """money_transfer_service depends on the account number, not the trust flag."""
        acc = self.RPB.create(
            {"acc_number": "BE40967000000063", "partner_id": self.partner_be.id}
        )
        before = acc.money_transfer_service
        acc.allow_out_payment = True
        acc.invalidate_recordset()
        self.assertEqual(acc.money_transfer_service, before)

    # -- transient display_name ------------------------------------------------

    def test_display_name_transient_record_has_no_literal_false(self):
        """display_name never renders the literal "False" on a NewId record."""
        new_rec = self.RPB.with_context(display_account_trust=True).new(
            {"partner_id": self.partner_fr.id}
        )
        self.assertNotIn("False", new_rec.display_name or "")

    # -- lock_trust_fields -----------------------------------------------------

    def test_lock_trust_fields(self):
        new_rec = self.RPB.new({"partner_id": self.partner_be.id})
        self.assertFalse(new_rec.lock_trust_fields, "new record is never locked")

        acc = self.RPB.create(
            {"acc_number": "BE71096123456769", "partner_id": self.partner_be.id}
        )
        self.assertFalse(acc.lock_trust_fields, "untrusted persisted account unlocked")
        acc.allow_out_payment = True
        self.assertTrue(acc.lock_trust_fields, "trusted persisted account locked")

    # -- trust rights (policy: BOTH directions need the group) -----------------

    def test_clerk_cannot_trust(self):
        acc = self.RPB.create(
            {"acc_number": "BE71096123456769", "partner_id": self.partner_be.id}
        )
        with self.assertRaises(UserError):
            acc.with_user(self.clerk).write({"allow_out_payment": True})

    def test_clerk_cannot_untrust(self):
        """Un-trusting an account also requires the trust group."""
        acc = self.RPB.create(
            {"acc_number": "BE71096123456769", "partner_id": self.partner_be.id}
        )
        acc.allow_out_payment = True
        with self.assertRaises(UserError):
            acc.with_user(self.clerk).write({"allow_out_payment": False})

    # -- archived-account guard in create() ------------------------------------

    def test_create_rejects_archived_duplicate(self):
        acc = self.RPB.create(
            {"acc_number": "BE68539007547034", "partner_id": self.partner_be.id}
        )
        acc.action_archive()
        with self.assertRaises(UserError):
            self.RPB.create(
                {"acc_number": "BE68539007547034", "partner_id": self.partner_be.id}
            )

    def test_create_rejects_archived_duplicate_ignoring_formatting(self):
        """A differently formatted number still collides with the archived one."""
        # The check keys on the sanitized number, so spaces/case still match.
        acc = self.RPB.create(
            {"acc_number": "BE68539007547034", "partner_id": self.partner_be.id}
        )
        acc.action_archive()
        with self.assertRaises(UserError):
            self.RPB.create(
                {
                    "acc_number": "be68 5390 0754 7034",
                    "partner_id": self.partner_be.id,
                }
            )

    def test_create_multi_detects_archived_duplicate(self):
        """A collision on ANY record of a batched create is detected."""
        # The guard runs one query for the whole batch, yet stays per-pair correct.
        acc = self.RPB.create(
            {"acc_number": "BE62510007547061", "partner_id": self.partner_be.id}
        )
        acc.action_archive()
        with self.assertRaises(UserError):
            self.RPB.create(
                [
                    {
                        "acc_number": "BE71096123456769",
                        "partner_id": self.partner_fr.id,
                    },
                    {
                        "acc_number": "BE62510007547061",
                        "partner_id": self.partner_be.id,
                    },
                ]
            )
