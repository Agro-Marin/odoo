from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestModel(TransactionCase):
    def setUp(self):
        self.env["html.field.history.test"].search([]).unlink()
        super().setUp()

    def test_html_field_history_write(self):
        rec1 = self.env["html.field.history.test"].create(
            {
                "versioned_field_1": "mock content",
            }
        )
        self.assertFalse(
            rec1.html_field_history,
            "Record creation should not generate revisions",
        )
        self.assertFalse(
            rec1.html_field_history_metadata,
            "We should never have metadata without revisions",
        )

        rec1.write(
            {
                "versioned_field_1": "mock content 2",
            }
        )
        self.assertEqual(len(rec1.html_field_history["versioned_field_1"]), 1)
        self.assertEqual(len(rec1.html_field_history_metadata["versioned_field_1"]), 1)
        self.assertEqual(rec1.versioned_field_1, "<p>mock content 2</p>")
        self.assertFalse(rec1.html_field_history["versioned_field_2"])
        self.assertFalse(rec1.html_field_history_metadata["versioned_field_2"])

        rec1.write(
            {
                "versioned_field_1": "mock content 3",
            }
        )
        rec1.write(
            {
                "versioned_field_1": None,
            }
        )
        self.assertEqual(len(rec1.html_field_history["versioned_field_1"]), 3)
        rec1.unlink()

        rec2 = self.env["html.field.history.test"].create(
            {
                "versioned_field_2": "mock content",
            }
        )
        self.assertFalse(
            rec2.html_field_history,
            "Record creation should not generate revisions",
        )
        self.assertFalse(
            rec2.html_field_history_metadata,
            "We should never have metadata without revisions",
        )

        with self.assertRaises(
            ValidationError,
            msg="We should not be able to versioned a field that is not declared as sanitize=True",
        ):
            rec2.write(
                {
                    "versioned_field_2": "mock content 2",
                }
            )

        rec2.unlink()

    def test_html_field_history_batch_write(self):
        rec1 = self.env["html.field.history.test"].create(
            {
                "versioned_field_1": "rec1 initial content",
                "versioned_field_2": "text",
            }
        )
        rec2 = self.env["html.field.history.test"].create(
            {
                "versioned_field_1": "rec2 initial value",
            }
        )

        rec_writes = (rec1 + rec2).write(
            {
                "versioned_field_1": "field has been batch overwritten",
            }
        )

        self.assertTrue(rec_writes, "Batch write should return True")

        self.assertEqual(len(rec1.html_field_history["versioned_field_1"]), 1)
        self.assertEqual(
            rec1.html_field_history["versioned_field_1"][0]["patch"],
            "R@1:<p>rec1 initial content",
        )
        self.assertEqual(len(rec1.html_field_history_metadata["versioned_field_1"]), 1)
        self.assertEqual(
            rec1.versioned_field_1, "<p>field has been batch overwritten</p>"
        )
        self.assertEqual(rec1.versioned_field_2, "text")

        self.assertEqual(len(rec2.html_field_history["versioned_field_1"]), 1)
        self.assertEqual(
            rec2.html_field_history["versioned_field_1"][0]["patch"],
            "R@1:<p>rec2 initial value",
        )
        self.assertEqual(len(rec2.html_field_history_metadata["versioned_field_1"]), 1)
        self.assertEqual(
            rec2.versioned_field_1, "<p>field has been batch overwritten</p>"
        )
        self.assertFalse(rec2.versioned_field_2)

        rec1.unlink()
        rec2.unlink()

    def test_html_field_history_revision_are_sanitized(self):
        rec1 = self.env["html.field.history.test"].create(
            {
                "versioned_field_1": "mock content",
            }
        )
        self.assertFalse(
            rec1.html_field_history,
            "Record creation should not generate revisions",
        )
        # Attempt to write unsecure HTML inside sanitized html field
        rec1.write(
            {"versioned_field_1": 'scam <iframe src="http://not.secure.scam" />'}
        )
        self.assertEqual(len(rec1.html_field_history["versioned_field_1"]), 1)
        self.assertEqual(rec1.versioned_field_1, "<p>scam </p>")
        self.assertNotIn("iframe", rec1.html_field_history["versioned_field_1"])
        self.assertNotIn(
            "not.secure.scam", rec1.html_field_history["versioned_field_1"]
        )

        # Ensure the unsecure HTML was not stored in revision data
        rec1.write({"versioned_field_1": "not a scam"})
        self.assertEqual(len(rec1.html_field_history["versioned_field_1"]), 2)
        self.assertEqual(rec1.versioned_field_1, "<p>not a scam</p>")
        self.assertNotIn("iframe", rec1.html_field_history["versioned_field_1"])
        self.assertNotIn(
            "not.secure.scam", rec1.html_field_history["versioned_field_1"]
        )
        rec1.unlink()


@tagged("-at_install", "post_install")
class TestHistoryRpcGuards(TransactionCase):
    """RPC-reachable guards and revision retrieval of the history mixin."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["html.field.history.test"].create(
            {"versioned_field_1": "<p>v1</p>"}
        )
        cls.record.versioned_field_1 = "<p>v2</p>"
        cls.record.versioned_field_1 = "<p>v3</p>"

    def test_unversioned_field_name_rejected(self):
        """A field outside _get_fields_versioned raises a clean UserError."""
        with self.assertRaises(UserError):
            self.record.html_field_history_get_content_at_revision("display_name", 1)

    def test_non_integer_revision_rejected(self):
        """Strings, None and booleans are rejected as revision ids."""
        for bogus in ("1", None, True):
            with self.assertRaises(UserError):
                self.record.html_field_history_get_content_at_revision(
                    "versioned_field_1", bogus
                )

    def test_content_restored_at_revision(self):
        """Applying stored patches walks the content back to a revision."""
        restored = self.record.html_field_history_get_content_at_revision(
            "versioned_field_1", 1
        )
        self.assertEqual(restored, "<p>v1</p>")

    def test_comparison_and_diff_reference_both_versions(self):
        """Comparison and unified diff expose old and new content."""
        comparison = self.record.html_field_history_get_comparison_at_revision(
            "versioned_field_1", 1
        )
        self.assertIn("v1", comparison)
        self.assertIn("v3", comparison)

        diff = self.record.html_field_history_get_unified_diff_at_revision(
            "versioned_field_1", 1
        )
        self.assertIn("v3", diff)
