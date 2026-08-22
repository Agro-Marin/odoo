"""``duration_tracking`` must follow the field whose changes produce it.

``mail.tracking.duration.mixin._compute_duration_tracking`` declared no
dependency at all. The buckets are rebuilt from ``mail.tracking.value`` rows in
raw SQL, and every one of those rows exists *because* the tracked many2one
changed -- so that field is the whole dependency, and without it the value was
computed once and never invalidated.

The window that matters is a single request: moving a record to another stage and
reading it back, which is exactly what a kanban drag-and-drop does. Before the
fix the client was handed the time spent in the *previous* stage.
"""

from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("mail_track", "post_install", "-at_install")
class TestDurationTrackingInvalidates(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer_a, cls.customer_b = cls.env["res.partner"].create(
            [
                {"name": "Duration Customer A"},
                {"name": "Duration Customer B"},
            ]
        )
        cls.record = cls.env["mail.test.track.duration.mixin"].create(
            {
                "name": "Duration Record",
                "customer_id": cls.customer_a.id,
            }
        )
        cls.env.flush_all()

    def test_duration_tracking_follows_the_tracked_field(self):
        # assert on which buckets exist, not on the seconds in them: a slow run
        # would make the durations non-zero and say nothing about invalidation
        self.assertEqual(
            set(self.record.duration_tracking),
            {str(self.customer_a.id)},
            "sanity: the record starts bucketed against its first customer",
        )

        self.record.customer_id = self.customer_b
        self.env.flush_all()

        self.assertEqual(
            set(self.record.duration_tracking),
            {str(self.customer_a.id), str(self.customer_b.id)},
            "the new value must gain a bucket without an explicit invalidation; "
            "the reading used to stop at the previous value's bucket alone",
        )

    def test_client_is_not_handed_a_stale_bucket(self):
        """The same thing through the entry point the web client actually uses."""
        self.assertTrue(self.record.duration_tracking)  # prime the cache

        result = self.record.web_save(
            {"customer_id": self.customer_b.id}, {"duration_tracking": {}}
        )

        self.record.invalidate_recordset()
        self.assertEqual(
            result[0]["duration_tracking"],
            self.record.duration_tracking,
            "web_save must return the recomputed buckets, not the cached ones",
        )

    def test_a_model_without_a_tracked_field_still_sets_up(self):
        """The dependency is resolved per model, so it must tolerate absence.

        ``mixin.mail.tracking.duration`` itself declares no
        ``_track_duration_field``; a callable ``@api.depends`` that assumed one
        would break registry setup rather than this assertion.
        """
        mixin = self.env["mixin.mail.tracking.duration"]
        self.assertEqual(mixin._get_duration_tracking_depends_fields(), [])
        self.assertEqual(
            self.env[
                "mail.test.track.duration.mixin"
            ]._get_fields_duration_tracking_depends(),
            ["customer_id"],
        )
