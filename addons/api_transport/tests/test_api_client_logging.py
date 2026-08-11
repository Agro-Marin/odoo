"""Tests for what APIGatewayClient writes to api.event.log.

The rows are readable by everyone in ``group_api_gateway_user``, so what lands
in them is a security boundary, not a debugging convenience. Two failures are
pinned here:

* a ``data=`` body bypassed redaction entirely, because the redactor walks
  dicts and lists and hands every other type straight back -- so a serialized
  JSON body was stored verbatim and a binary one raised TypeError;
* that TypeError escaped ``_log_request`` into ``request``'s bare
  ``except Exception``, which counted the *successful* call as a credential
  failure and then re-entered the same failing code with nothing left to catch
  it.
"""

from unittest.mock import MagicMock, patch

import requests

from odoo.libs.logging import mute_logger
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.api_transport.tools.api_client import _MAX_LOGGED_PAYLOAD
from odoo.addons.api_transport.tools.exceptions import CommError

SECRET_KEY = "-----BEGIN PRIVATE KEY-----MIIEvQIBADANBg"


def _ok_response():
    """A minimal 200 with a JSON body, as ``requests`` would hand it back."""
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"status": "success"}
    response.text = '{"status": "success"}'
    response.raise_for_status.return_value = None
    return response


class ClientLoggingCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["api.endpoint.outbound"].create(
            {
                "name": "Payload Probe",
                "code": "payload_probe",
                "endpoint_url": "https://example.invalid/live",
                "auth_type": "none",
                "environment": "production",
            }
        )

    def _client(self):
        return self.service._get_api_client()


@tagged("post_install", "-at_install")
class TestPayloadSerialization(ClientLoggingCommon):
    """``_serialize_payload_for_log`` over every shape a body arrives in."""

    def test_dict_body_is_redacted_key_by_key(self):
        """A ``json=`` body: the pre-existing behaviour, unchanged."""
        out = self._client()._serialize_payload_for_log(
            {"rfc": "XAXX010101000", "password": "s3cr3t"},
        )
        self.assertIn("XAXX010101000", out)
        self.assertNotIn("s3cr3t", out)
        self.assertIn("***REDACTED***", out)

    def test_json_bytes_body_is_parsed_and_redacted(self):
        """``data=<bytes>`` used to raise TypeError instead of being redacted."""
        out = self._client()._serialize_payload_for_log(
            b'{"uuid": "abc-123", "password": "s3cr3t"}',
        )
        self.assertIn("abc-123", out)
        self.assertNotIn("s3cr3t", out)

    def test_json_str_body_is_parsed_and_redacted(self):
        """``data=<str>`` used to be stored verbatim, secrets included."""
        out = self._client()._serialize_payload_for_log(
            '{"uuid": "abc-123", "password": "s3cr3t"}',
        )
        self.assertIn("abc-123", out)
        self.assertNotIn("s3cr3t", out)

    def test_key_material_under_an_unmatched_name_is_still_not_stored(self):
        """The redactor matches key *names*, and real payloads invent their own.

        ``l10n_mx_edi``'s SW cancellation posts the unencrypted CSD private key
        as ``b64Key``, which matches none of ``_SENSITIVE_FIELD_PATTERNS``. That
        is a real gap in the name-matching approach; what this pins is only that
        the serialized form of that payload does not reach the row -- an
        unparseable body is recorded by size.
        """
        out = self._client()._serialize_payload_for_log(
            f"rfc=XAXX010101000&b64Key={SECRET_KEY}".encode(),
        )
        self.assertNotIn(SECRET_KEY, out)
        self.assertIn("not logged", out)

    def test_binary_body_is_recorded_by_size_only(self):
        """Raw audio for a transcription call: never decodable, never stored."""
        out = self._client()._serialize_payload_for_log(
            b"\x49\x44\x33" + bytes(range(256))
        )
        self.assertIn("259 bytes", out)
        self.assertIn("not logged", out)

    def test_unparseable_text_body_is_recorded_by_size_only(self):
        out = self._client()._serialize_payload_for_log("<xml>not json</xml>")
        self.assertIn("19 chars", out)
        self.assertIn("not logged", out)

    def test_json_scalar_is_not_mistaken_for_structure(self):
        """``json.loads('"x"')`` yields a str, which the redactor cannot walk."""
        out = self._client()._serialize_payload_for_log('"just a string"')
        self.assertIn("not logged", out)

    def test_uninspectable_body_is_not_consumed(self):
        """A stream must be described, not read: reading it would empty it."""
        body = (chunk for chunk in (b"a", b"b"))
        out = self._client()._serialize_payload_for_log(body)
        self.assertIn("generator", out)
        self.assertEqual(list(body), [b"a", b"b"])

    def test_empty_body_is_empty_string(self):
        self.assertEqual(self._client()._serialize_payload_for_log(None), "")
        self.assertEqual(self._client()._serialize_payload_for_log(b""), "")

    def test_large_body_is_capped(self):
        out = self._client()._serialize_payload_for_log({"k": "v" * 40000})
        self.assertEqual(len(out), _MAX_LOGGED_PAYLOAD)


@tagged("post_install", "-at_install")
class TestUsageTrackingOnAnUnauthenticatedService(ClientLoggingCommon):
    """``auth_type = 'none'`` means no credential to increment.

    ``increment_usage`` calls ``ensure_one``, so on the success path an empty
    recordset raised ValueError *after* the call had gone out -- and the bare
    ``except Exception`` that caught it called the same method again. Three
    services ship in this state (``syngenta``, the SAT blocklist, PubChem), so
    this was every call any of them made.
    """

    def test_the_service_under_test_really_has_no_credential(self):
        self.assertFalse(self._client().credential)

    @patch("requests.Session.request")
    def test_a_successful_call_returns_its_response(self, mock_request):
        mock_request.return_value = _ok_response()

        result = self._client().post("/report", json={"rows": []})

        self.assertEqual(result["status_code"], 200)

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_failing_call_still_raises_the_transport_error(self, mock_request):
        """The error the caller is written against, not ValueError."""
        mock_request.side_effect = requests.exceptions.ConnectionError("down")

        with self.assertRaises(CommError):
            self._client().post("/report", json={"rows": []})


@tagged("post_install", "-at_install")
class TestLoggingCannotFailTheRequest(ClientLoggingCommon):
    """``_log_request`` runs after the exchange; it must never undo it."""

    def _queued(self):
        return self.env.cr.precommit.data.get("api.event.log.values") or []

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    def test_a_broken_serializer_does_not_raise(self):
        client = self._client()
        with patch.object(
            type(client),
            "_serialize_payload_for_log",
            side_effect=RuntimeError("boom"),
        ):
            client._log_request("POST", "https://example.invalid/x", {}, None, "t-1")
        self.assertEqual(self._queued(), [], "nothing should have been queued")

    @patch("requests.Session.request")
    def test_a_binary_body_neither_crashes_nor_fails_the_credential(self, mock_request):
        """The regression: HTTP 200, then TypeError on the way out.

        The call had already happened -- the vendor had been paid and the side
        effect taken -- yet the caller saw a raw TypeError, the credential was
        marked failed, and no row was written at all.
        """
        mock_request.return_value = _ok_response()

        client = self._client()
        result = client.post("/listen", data=b"\x00\x01\x02audio")

        self.assertEqual(result["body"], {"status": "success"})
        rows = self._queued()
        self.assertEqual(len(rows), 1, "the exchange should be recorded")
        self.assertNotEqual(rows[0]["state"], "failed")
        self.assertIn("not logged", rows[0]["request_payload"])

    @patch("requests.Session.request")
    def test_a_serialized_json_body_is_redacted_in_the_row(self, mock_request):
        mock_request.return_value = _ok_response()

        client = self._client()
        client.post("/cancel", data=b'{"uuid": "abc-123", "password": "s3cr3t"}')

        rows = self._queued()
        self.assertEqual(len(rows), 1)
        self.assertIn("abc-123", rows[0]["request_payload"])
        self.assertNotIn("s3cr3t", rows[0]["request_payload"])
