from odoo import fields
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestApprovalRateLimit(ApprovalCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company_currency = cls.company.currency_id
        cls.foreign = (
            cls.env["res.currency"]
            .with_context(active_test=False)
            .search([("id", "!=", cls.company_currency.id)], limit=1)
        )
        cls.foreign.active = True
        cls.foreign.rate_ids.unlink()
        cls.foreign.write(
            {
                "rate_ids": [
                    (
                        0,
                        0,
                        {
                            "name": fields.Date.today(),
                            "rate": 0.1,
                            "company_id": cls.company.id,
                        },
                    ),
                ],
            },
        )

    def _doc(self, amount_total, currency=None, state="draft"):
        return self.env["approval.test.document"].create(
            {
                "name": "RL doc",
                "partner_id": self.partner.id,
                "company_id": self.company.id,
                "currency_id": (currency or self.company_currency).id,
                "amount_total": amount_total,
                "state": state,
            },
        )

    def _exceeded(self, doc, **kwargs):
        params = {
            "hours": 24,
            "max_count": 99,
            "max_amount": 1_000_000.0,
            "under_threshold_amount": 1000.0,
        }
        params.update(kwargs)
        return doc._approval_rate_limit_exceeded(**params)

    def test_sanity_of_the_rate_fixture(self):
        today = fields.Date.today()
        self.assertAlmostEqual(
            self.foreign._convert(90, self.company_currency, self.company, today),
            900.0,
            places=2,
        )
        self.assertAlmostEqual(
            self.company_currency._convert(1000, self.foreign, self.company, today),
            100.0,
            places=2,
        )

    def test_foreign_amounts_are_converted_before_being_summed(self):
        self._doc(90, self.foreign)
        current = self._doc(200)
        self.assertTrue(
            self._exceeded(current, max_amount=1000.0),
            "cumulative amounts must be converted into company currency",
        )

    def test_threshold_is_converted_into_each_document_currency(self):
        self._doc(150, self.foreign)
        current = self._doc(10)
        self.assertFalse(
            self._exceeded(current, max_count=2, max_amount=1_000_000.0),
            "a document above the threshold in company terms must not count",
        )

    def test_count_limit_trips_on_under_threshold_documents(self):
        for _ in range(3):
            self._doc(100)
        current = self._doc(100)
        self.assertTrue(self._exceeded(current, max_count=3))

    def test_count_limit_ignores_documents_above_the_threshold(self):
        for _ in range(3):
            self._doc(5000)
        current = self._doc(100)
        self.assertFalse(
            self._exceeded(current, max_count=3),
            "only documents BELOW the threshold count toward the pattern",
        )

    def test_excluded_states_are_ignored(self):
        for _ in range(3):
            self._doc(100, state="rejected")
        current = self._doc(100)
        self.assertFalse(
            self._exceeded(current, max_count=3, excluded_states=("rejected",)),
        )

    def test_the_document_itself_is_not_double_counted(self):
        current = self._doc(600)
        self.assertFalse(
            self._exceeded(current, max_amount=1000.0),
            "the document under test must be excluded from its own window",
        )

    def test_window_excludes_older_documents(self):
        old = self._doc(900)
        self.env.cr.execute(
            "UPDATE approval_test_document SET create_date = now() - interval "
            "'48 hours' WHERE id = %s",
            [old.id],
        )
        old.invalidate_recordset(["create_date"])
        current = self._doc(200)
        self.assertFalse(
            self._exceeded(current, hours=24, max_amount=1000.0),
            "documents outside the look-back window must not count",
        )

    def test_limit_is_per_creator(self):
        other = (
            self.env["approval.test.document"]
            .with_user(self.approver_1)
            .sudo()
            .create(
                {
                    "name": "RL other",
                    "partner_id": self.partner.id,
                    "company_id": self.company.id,
                    "currency_id": self.company_currency.id,
                    "amount_total": 900,
                },
            )
        )
        self.assertEqual(other.create_uid, self.approver_1)
        current = self._doc(200)
        self.assertFalse(
            self._exceeded(current, max_amount=1000.0),
            "another user's documents must not count against this creator",
        )
