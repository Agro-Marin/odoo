from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.api_ai.tests.common import credential_for
from odoo.addons.api_ai.tools.ai_clients import GroqClient, OpenAIClient
from odoo.addons.api_ai.tools.ai_clients.deepseek import DeepSeekClient
from odoo.addons.api_ai.tools.vendor_catalog import (
    PROVIDERS,
    build_whisper_form,
    read_whisper_transcript,
)
from odoo.addons.api_transport.tools.exceptions import CommError


@tagged("post_install", "-at_install")
class TestWhisperFormAndReader(TransactionCase):
    def test_the_form_always_asks_for_text(self):
        form = build_whisper_form("whisper-1", language="es")
        self.assertEqual(form["response_format"], "text")
        self.assertEqual(form["model"], "whisper-1")
        self.assertEqual(form["language"], "es")
        self.assertNotIn("prompt", form, "an absent hint must not be sent empty")

    def test_the_form_carries_a_vocabulary_hint(self):
        self.assertEqual(
            build_whisper_form("whisper-1", prompt="tarima, romana")["prompt"],
            "tarima, romana",
        )

    def test_the_reader_names_why_a_response_is_unusable(self):
        for payload, expected in (
            (None, "no response"),
            ({"text": "hi"}, "expected text"),
            ("   ", "empty transcript"),
        ):
            with self.subTest(payload=payload):
                text, problem = read_whisper_transcript(payload)
                self.assertIsNone(text)
                self.assertIn(expected, problem)

    def test_the_reader_strips_and_returns(self):
        text, problem = read_whisper_transcript("  hola mundo \n")
        self.assertEqual(text, "hola mundo")
        self.assertIsNone(problem)


@tagged("post_install", "-at_install")
class TestOpenAICompatibleTranscribe(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        credential_for(cls.env, "openai", bearer_token="K")

    def _client(self, cls=OpenAIClient):
        return cls(self.env)

    def test_it_posts_the_catalog_wire(self):
        client = self._client()
        sent = {}

        def fake_post(path, **kwargs):
            sent["path"] = path
            sent.update(kwargs)
            return {"status_code": 200, "body": "hola mundo"}

        with patch.object(client._client, "post", side_effect=fake_post):
            result = client.transcribe(b"AUDIO", "note.ogg", language="es")

        spec = PROVIDERS["openai"]
        self.assertEqual(result, "hola mundo")
        self.assertEqual(sent["path"], spec["audio_path"])
        self.assertEqual(sent["data"]["model"], spec["audio_model"])
        self.assertEqual(sent["data"]["response_format"], "text")
        self.assertEqual(sent["files"]["file"][0], "note.ogg")
        self.assertEqual(
            sent["files"]["file"][2], "audio/ogg", "the mime type is sniffed"
        )

    def test_an_unusable_response_raises_rather_than_returning_none(self):
        client = self._client()
        with patch.object(
            client._client, "post", return_value={"status_code": 200, "body": ""}
        ):
            with self.assertRaises(CommError) as caught:
                client.transcribe(b"AUDIO", "note.ogg")
        self.assertIn("no usable transcript", str(caught.exception))

    def test_empty_audio_is_refused_before_the_request(self):
        client = self._client()
        with patch.object(client._client, "post") as post:
            with self.assertRaises(CommError):
                client.transcribe(b"", "note.ogg")
        post.assert_not_called()

    def test_a_vendor_without_an_audio_wire_says_so(self):
        credential_for(self.env, "deepseek", bearer_token="K")
        client = self._client(DeepSeekClient)
        with self.assertRaises(CommError) as caught:
            client.transcribe(b"AUDIO", "note.ogg")
        self.assertIn("no audio wire", str(caught.exception))

    def test_groq_transcribes_on_its_own_endpoint(self):
        credential_for(self.env, "groq", bearer_token="K")
        client = self._client(GroqClient)
        with patch.object(
            client._client,
            "post",
            return_value={"status_code": 200, "body": "transcrito"},
        ) as post:
            self.assertEqual(client.transcribe(b"AUDIO", "n.ogg"), "transcrito")
        self.assertEqual(
            post.call_args.kwargs["data"]["model"], PROVIDERS["groq"]["audio_model"]
        )
