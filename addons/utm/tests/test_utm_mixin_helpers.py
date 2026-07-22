"""Tests for the UTM mixin find-or-create and name helpers."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUtmMixinHelpers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mixin = cls.env["utm.mixin"]

    def test_split_name_without_counter(self):
        """A bare name has an implicit counter of 1."""
        self.assertEqual(self.Mixin._split_name_and_count("Medium"), ("Medium", 1))

    def test_split_name_with_counter(self):
        """A '[n]' suffix is parsed as the counter."""
        self.assertEqual(
            self.Mixin._split_name_and_count("Medium [1234]"), ("Medium", 1234)
        )

    def test_find_or_create_is_idempotent(self):
        """A second lookup of the same name returns the same record."""
        first = self.Mixin._find_or_create_record("utm.source", "Loop test source")
        second = self.Mixin._find_or_create_record("utm.source", "loop test source")
        self.assertEqual(first, second)

    def test_find_or_create_record_payload(self):
        """The frontend wrapper returns the record id and display name."""
        payload = self.Mixin.find_or_create_record("utm.medium", "Loop test medium")
        self.assertIn("id", payload)
        self.assertEqual(payload["name"], "Loop test medium")

    def test_unique_names_increments_duplicates(self):
        """Duplicate names get incrementing counters in order."""
        result = self.Mixin._get_unique_names(
            "utm.source", ["ZZ uniq", "ZZ uniq", "ZZ uniq"]
        )
        self.assertEqual(result[0], "ZZ uniq")
        self.assertEqual(result[1], "ZZ uniq [2]")
        self.assertEqual(result[2], "ZZ uniq [3]")
