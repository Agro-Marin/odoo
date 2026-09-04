from odoo.libs.documents import (
    CUES,
    EXPENSIVE,
    BaseReader,
    Cue,
    register_reader,
    unregister_reader,
)
from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.speech.tools.engines import SPOKEN_MIMETYPES


class StubTranscription(BaseReader):
    name = "stub_call_transcription"
    mimetypes = SPOKEN_MIMETYPES
    yields = (CUES,)
    cost = EXPENSIVE

    def read(self, document):
        return [Cue(0.0, 2.0, "can you hear me", "")]


@tagged("post_install", "-at_install")
class TestCallRecording(MailCommon):
    def setUp(self):
        super().setUp()
        engine = register_reader(StubTranscription())
        self.addCleanup(unregister_reader, engine)
        self.channel = self.env["discuss.channel"]._create_channel(
            name="Recorded", group_id=None
        )

    def _audio(self, name="chunk.webm"):
        return self.env["ir.attachment"].create(
            {"name": name, "mimetype": "audio/webm", "raw": b"chunk"}
        )

    def test_a_call_owns_the_media_it_records(self):
        history = self.env["discuss.call.history"].create(
            {"channel_id": self.channel.id, "start_dt": "2026-09-03 10:00:00"}
        )
        history._add_media_segment(self._audio(), 0, 5000)
        self.assertEqual(history.media_duration_ms, 5000)
        self.assertTrue(history.has_media)

    def test_recording_a_chunk_opens_a_call_history_when_none_is_open(self):
        segment = self.channel._record_call_media(self._audio(), 0, 5000)
        history = segment._owner()
        self.assertEqual(history._name, "discuss.call.history")
        self.assertEqual(history.channel_id, self.channel)

    def test_a_second_chunk_joins_the_call_already_open(self):
        first = self.channel._record_call_media(self._audio("a.webm"), 0, 5000)
        second = self.channel._record_call_media(self._audio("b.webm"), 5000, 9000)
        self.assertEqual(first._owner(), second._owner())
        self.assertEqual(first._owner().media_duration_ms, 9000)

    def test_a_transcribed_call_reads_back_as_one_transcript(self):
        segment = self.channel._record_call_media(self._audio(), 0, 5000)
        segment.attachment_id._transcribe()
        self.assertEqual(segment._owner().transcript, "can you hear me")
        self.assertEqual(segment._owner().transcription_state, "done")

    def test_what_was_said_in_a_call_is_searchable(self):
        segment = self.channel._record_call_media(self._audio(), 0, 5000)
        segment.attachment_id._transcribe()
        found = self.env["ir.attachment"].search(
            [
                ("id", "=", segment.attachment_id.id),
                ("index_content", "ilike", "hear me"),
            ]
        )
        self.assertEqual(found, segment.attachment_id)

    def test_a_call_history_gained_the_timeline_without_declaring_it(self):
        history = self.env["discuss.call.history"]
        for field in ("segment_ids", "transcript", "media_duration_ms", "has_media"):
            self.assertIn(field, history._fields)

    def test_a_chunk_that_overlaps_the_one_before_it_is_refused(self):
        self.channel._record_call_media(self._audio("a.webm"), 0, 5000)
        with self.assertRaises(Exception):
            self.channel._record_call_media(self._audio("b.webm"), 4000, 9000)
