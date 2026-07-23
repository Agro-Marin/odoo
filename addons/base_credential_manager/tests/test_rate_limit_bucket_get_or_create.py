# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGetOrCreateBucket(TransactionCase):
    """rate.limit.bucket.get_or_create_bucket keying and idempotency."""

    def test_creates_then_reuses_global_bucket(self):
        """First call creates a full bucket; the second returns the same row."""
        Bucket = self.env["rate.limit.bucket"]
        endpoint = self.env["res.partner"].create({"name": "Endpoint"})
        bucket = Bucket.get_or_create_bucket(endpoint, company_id=None)
        self.assertTrue(bucket)
        self.assertEqual(bucket.bucket_key, f"res.partner:{endpoint.id}:global")
        self.assertEqual(bucket.tokens, 100.0)  # default capacity
        again = Bucket.get_or_create_bucket(endpoint, company_id=None)
        self.assertEqual(again, bucket)

    def test_company_scoped_bucket_key(self):
        """A company id yields a company-scoped bucket key."""
        Bucket = self.env["rate.limit.bucket"]
        endpoint = self.env["res.partner"].create({"name": "Endpoint2"})
        bucket = Bucket.get_or_create_bucket(endpoint, company_id=self.env.company.id)
        self.assertEqual(
            bucket.bucket_key,
            f"res.partner:{endpoint.id}:{self.env.company.id}",
        )
