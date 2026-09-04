from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import SpeechCase


@tagged("post_install", "-at_install")
class TestMediaSegment(SpeechCase):
    def test_two_segments_may_not_cover_the_same_moment(self):
        recording = self._recording()
        recording._add_media_segment(self._audio("a.mp3"), 0, 2000)
        with self.assertRaises(ValidationError):
            recording._add_media_segment(self._audio("b.mp3"), 1500, 3000)

    def test_segments_that_touch_do_not_overlap(self):
        recording = self._recording()
        recording._add_media_segment(self._audio("a.mp3"), 0, 2000)
        recording._add_media_segment(self._audio("b.mp3"), 2000, 4000)
        self.assertEqual(len(recording.segment_ids), 2)

    def test_two_owners_may_hold_the_same_moment(self):
        first = self._recording("first")
        second = self._recording("second")
        first._add_media_segment(self._audio("a.mp3"), 0, 2000)
        second._add_media_segment(self._audio("b.mp3"), 0, 2000)
        self.assertEqual(len(first.segment_ids), 1)
        self.assertEqual(len(second.segment_ids), 1)

    def test_a_segment_must_end_after_it_starts(self):
        recording = self._recording()
        with self.assertRaises(Exception):
            recording._add_media_segment(self._audio(), 2000, 2000)

    def test_deleting_a_segment_deletes_its_media(self):
        recording = self._recording()
        attachment = self._audio()
        segment = recording._add_media_segment(attachment, 0, 1000)
        segment.unlink()
        self.assertFalse(attachment.exists())

    def test_deleting_the_owner_deletes_its_segments(self):
        recording = self._recording()
        recording._add_media_segment(self._audio(), 0, 1000)
        segments = self.env["media.segment"]._of(recording)
        recording.unlink()
        self.assertFalse(segments.exists())

    def test_one_media_file_belongs_to_one_segment(self):
        first = self._recording("first")
        second = self._recording("second")
        attachment = self._audio()
        first._add_media_segment(attachment, 0, 1000)
        with self.assertRaises(Exception):
            second._add_media_segment(attachment, 0, 1000)

    def test_a_segment_knows_its_owner(self):
        recording = self._recording()
        segment = recording._add_media_segment(self._audio(), 0, 1000)
        self.assertEqual(segment._owner(), recording)

    def test_duration_is_the_span_it_covers(self):
        recording = self._recording()
        segment = recording._add_media_segment(self._audio(), 500, 2000)
        self.assertEqual(segment.duration_ms, 1500)


class TestSegmentOwnership(SpeechCase):
    def setUp(self):
        super().setUp()
        self.stranger = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "stranger",
                    "login": "speech_stranger",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )

    def _as_stranger(self):
        return self.env(user=self.stranger, su=False)

    def test_a_stranger_may_not_file_media_against_a_record_they_cannot_write(self):
        recording = self._recording()
        attachment = self._audio()
        with self.assertRaises(ValidationError):
            self._as_stranger()["media.segment"].create(
                {
                    "res_model": recording._name,
                    "res_id": recording.id,
                    "attachment_id": attachment.id,
                    "start_ms": 0,
                    "end_ms": 1000,
                }
            )

    def test_the_recorder_files_media_under_sudo_and_is_not_refused(self):
        recording = self._recording()
        segment = recording._add_media_segment(self._audio(), 0, 1000)
        self.assertTrue(segment.id)
        self.assertEqual(segment._owner(), recording)

    def test_the_constraint_runs_at_all(self):
        method = next(
            check
            for check in self.env["media.segment"]._constraint_methods
            if check.__name__ == "_constrains_the_owner_is_writable"
        )
        self.assertFalse(
            getattr(method, "_constrains_sudo", True),
            "the owner check must be declared sudo=False or it never runs",
        )
