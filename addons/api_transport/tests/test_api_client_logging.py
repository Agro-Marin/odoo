"""Tests for what APIGatewayClient writes to api.event.log.

The rows are readable by everyone in ``group_api_gateway_user``, so what lands
in them is a security boundary, not a debugging convenience.

Fixed behaviour pinned here:

* a ``data=`` body bypassed redaction entirely, because the redactor walks
  dicts and lists and hands every other type straight back -- so a serialized
  JSON body was stored verbatim and a binary one raised TypeError;
* that TypeError escaped ``_log_request`` into ``request``'s bare
  ``except Exception``, which counted the *successful* call as a credential
  failure and then re-entered the same failing code with nothing left to catch
  it;
* ``increment_usage`` calls ``ensure_one``, so the same double-fault fired one
  line earlier for any service with no credential to increment.

Behaviour that exists for callers whose APIs do not fit the happy path:

* ``raise_for_status=False``, for a 4xx whose body is what you came for;
* ``log_request_payload``, for a body that is secret whatever it names its
  fields.
"""

import json
from unittest.mock import MagicMock, patch

import requests
from requests.auth import HTTPDigestAuth

from odoo.exceptions import UserError, ValidationError
from odoo.libs.logging import mute_logger
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.api_transport.tools.api_client import _MAX_LOGGED_PAYLOAD
from odoo.addons.api_transport.tools.exceptions import ClientError, CommError

SECRET_KEY = "-----BEGIN PRIVATE KEY-----MIIEvQIBADANBg"

# Deliberately long and distinctive. These tests assert a secret appears nowhere
# in a serialized payload, and a short needle finds itself by chance in anything
# high-entropy the payload also carries -- a two-character passphrase turned up
# inside a base64 certificate in about a third of runs of a sibling test, failing
# it as a key leak while the redaction was working perfectly. The haystacks here
# are small and deterministic, so this is insurance rather than a fix; the reason
# it matters is that these are the tests someone copies to prove their own
# payload is redacted, and theirs may not be.
SECRET_VALUE = "redaction-probe-must-never-appear"

# What SW answers with when the CFDI was already stamped: HTTP 400, and the
# signed XML the caller wanted sitting in messageDetail.
SW_ALREADY_STAMPED = {
    "status": "error",
    "message": "307 - El comprobante contiene un timbre previo",
    "messageDetail": "<cfdi:Comprobante>…already signed…</cfdi:Comprobante>",
    "data": None,
}


def _ok_response():
    """A minimal 200 with a JSON body, as ``requests`` would hand it back."""
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"status": "success"}
    response.text = '{"status": "success"}'
    response.raise_for_status.return_value = None
    return response


def _error_response(status_code, json_data):
    """A 4xx/5xx carrying a JSON body, whose raise_for_status really raises."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.json.return_value = json_data
    response.text = json.dumps(json_data)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        f"{status_code} Client Error", response=response
    )
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
            {"rfc": "XAXX010101000", "password": SECRET_VALUE},
        )
        self.assertIn("XAXX010101000", out)
        self.assertNotIn(SECRET_VALUE, out)
        self.assertIn("***REDACTED***", out)

    def test_json_bytes_body_is_parsed_and_redacted(self):
        """``data=<bytes>`` used to raise TypeError instead of being redacted."""
        out = self._client()._serialize_payload_for_log(
            json.dumps({"uuid": "abc-123", "password": SECRET_VALUE}).encode(),
        )
        self.assertIn("abc-123", out)
        self.assertNotIn(SECRET_VALUE, out)

    def test_json_str_body_is_parsed_and_redacted(self):
        """``data=<str>`` used to be stored verbatim, secrets included."""
        out = self._client()._serialize_payload_for_log(
            json.dumps({"uuid": "abc-123", "password": SECRET_VALUE}),
        )
        self.assertIn("abc-123", out)
        self.assertNotIn(SECRET_VALUE, out)

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
        client.post(
            "/cancel",
            data=json.dumps({"uuid": "abc-123", "password": SECRET_VALUE}).encode(),
        )

        rows = self._queued()
        self.assertEqual(len(rows), 1)
        self.assertIn("abc-123", rows[0]["request_payload"])
        self.assertNotIn(SECRET_VALUE, rows[0]["request_payload"])


@tagged("post_install", "-at_install")
class TestRaiseForStatus(ClientLoggingCommon):
    """``raise_for_status=False``: a 4xx whose body is the point.

    SW, the Mexican PAC, reports an already-stamped CFDI as HTTP 400 with the
    signed XML in ``messageDetail``. Raising discards it -- ``_extract_error``
    keeps ``message`` alone -- so the caller loses the document it asked for.
    """

    def _queued(self):
        return self.env.cr.precommit.data.get("api.event.log.values") or []

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_4xx_still_raises_by_default(self, mock_request):
        """The default is unchanged: nothing existing has to opt back in."""
        mock_request.return_value = _error_response(400, SW_ALREADY_STAMPED)

        with self.assertRaises(ClientError):
            self._client().post("/stamp", json={})

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_4xx_is_returned_when_asked(self, mock_request):
        mock_request.return_value = _error_response(400, SW_ALREADY_STAMPED)

        result = self._client().post("/stamp", json={}, raise_for_status=False)

        self.assertEqual(result["status_code"], 400)
        self.assertEqual(result["body"]["status"], "error")

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_the_recoverable_detail_survives(self, mock_request):
        """The whole point: ``messageDetail`` is what raising threw away."""
        mock_request.return_value = _error_response(400, SW_ALREADY_STAMPED)

        result = self._client().post("/stamp", json={}, raise_for_status=False)

        self.assertIn("already signed", result["body"]["messageDetail"])

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_not_raising_is_still_a_failure_in_the_audit_trail(self, mock_request):
        """Control flow changes; the record of what happened does not."""
        mock_request.return_value = _error_response(400, SW_ALREADY_STAMPED)

        self._client().post("/stamp", json={}, raise_for_status=False)

        rows = self._queued()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "failed")
        self.assertEqual(rows[0]["error_type"], "validation")
        self.assertEqual(rows[0]["status_code"], 400)

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_status_maps_onto_the_declared_error_types(self, mock_request):
        """``error_type`` is a selection; an undeclared value rolls the batch back."""
        for status, expected in ((401, "auth"), (429, "rate_limit"), (503, "server")):
            with self.subTest(status=status):
                self.env.cr.precommit.data.pop("api.event.log.values", None)
                mock_request.return_value = _error_response(status, {"m": "no"})

                self._client().get("/probe", raise_for_status=False)

                self.assertEqual(self._queued()[-1]["error_type"], expected)

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_2xx_is_unaffected_by_the_flag(self, mock_request):
        mock_request.return_value = _ok_response()

        result = self._client().post("/stamp", json={}, raise_for_status=False)

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(self._queued()[0]["state"], "success")


@tagged("post_install", "-at_install")
class TestSuppressedRequestPayload(ClientLoggingCommon):
    """``log_request_payload = False`` for bodies that are secret by shape.

    Redaction matches key *names*, so it cannot protect a payload whose names
    it has never seen -- ``l10n_mx_edi`` posts the unencrypted CSD private key
    as ``b64Key``, which matches nothing in ``_SENSITIVE_FIELD_PATTERNS``. A
    service whose bodies are key material by construction opts out instead of
    hoping the pattern list keeps up.
    """

    def _queued(self):
        return self.env.cr.precommit.data.get("api.event.log.values") or []

    def test_the_flag_defaults_to_storing_bodies(self):
        self.assertTrue(self.service.log_request_payload)

    @patch("requests.Session.request")
    def test_the_body_is_not_stored_when_suppressed(self, mock_request):
        mock_request.return_value = _ok_response()
        self.service.log_request_payload = False

        self._client().post("/cancel", json={"b64Key": SECRET_KEY, "uuid": "abc-123"})

        payload = self._queued()[0]["request_payload"]
        self.assertNotIn(SECRET_KEY, payload)
        self.assertIn("suppressed", payload)

    @patch("requests.Session.request")
    def test_the_rest_of_the_exchange_is_still_recorded(self, mock_request):
        """Suppressing the body must not cost the audit trail everything else."""
        mock_request.return_value = _ok_response()
        self.service.log_request_payload = False

        self._client().post("/cancel", json={"b64Key": SECRET_KEY})

        row = self._queued()[0]
        self.assertEqual(row["status_code"], 200)
        self.assertEqual(row["request_method"], "POST")
        self.assertIn("/cancel", row["request_url"])
        self.assertTrue(row["trace_id"])

    @patch("requests.Session.request")
    def test_known_gap_the_name_based_redactor_does_not_catch_b64key(
        self, mock_request
    ):
        """Characterises the limitation the flag exists to work around.

        This asserts today's behaviour, not desired behaviour: ``b64Key`` is
        real key material and it does reach the row. Widening
        ``_SENSITIVE_FIELD_PATTERNS`` would break this test, which is the point
        -- it should be a deliberate change, not a silent one, and the opt-out
        above is what protects the payload meanwhile.
        """
        mock_request.return_value = _ok_response()

        self._client().post("/cancel", json={"b64Key": SECRET_KEY})

        self.assertIn(SECRET_KEY, self._queued()[0]["request_payload"])


@tagged("post_install", "-at_install")
class TestRawPassthroughLogging(ClientLoggingCommon):
    """``raw=True`` hands the caller the live Response; the row is metadata.

    The body is deliberately absent -- reading it would consume the stream the
    caller asked for intact -- but everything around it must still be there.
    Passing no response at all left the row on its "pending" default, so a
    completed exchange was recorded as one that never came back.
    """

    def _queued(self):
        return self.env.cr.precommit.data.get("api.event.log.values") or []

    @patch("requests.Session.request")
    def test_a_raw_call_records_status_and_timing(self, mock_request):
        mock_request.return_value = _ok_response()

        self._client().request("GET", "/stream", raw=True)

        row = self._queued()[0]
        self.assertEqual(row["state"], "success")
        self.assertEqual(row["status_code"], 200)
        self.assertIn("duration_ms", row)

    @patch("requests.Session.request")
    def test_a_raw_call_does_not_read_the_body(self, mock_request):
        response = _ok_response()
        mock_request.return_value = response

        self._client().request("GET", "/stream", raw=True)

        response.json.assert_not_called()
        self.assertEqual(self._queued()[0]["response_payload"], "null")

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_raw_4xx_is_recorded_as_failed(self, mock_request):
        mock_request.return_value = _error_response(503, {"m": "down"})

        self._client().request("GET", "/stream", raw=True, raise_for_status=False)

        row = self._queued()[0]
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["status_code"], 503)
        self.assertEqual(row["error_type"], "server")


@tagged("post_install", "-at_install")
class TestErrorMessagesDoNotLeakCredentials(ClientLoggingCommon):
    """``error_message`` was the one field on the row that was not masked.

    ``request_url``, request/response headers and both payloads are all
    redacted before they are stored. The error text was not, and for a
    connection or timeout failure ``requests`` builds that text out of the full
    request URL -- so a credential carried in the URL landed verbatim in a row
    that every monitoring user can read.

    Telegram is the concrete case: the bot token is a path segment, which is
    why the module bypassed the transport for downloads rather than route them
    through it.
    """

    TOKEN = "AAHsecretTOKENvalue"
    URL = f"https://api.telegram.org/file/bot123456:{TOKEN}/photo.jpg"

    def _last_log(self):
        self.env.cr.precommit.run()
        return self.env["api.event.log"].search([], order="id desc", limit=1)

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_connection_error_does_not_store_the_token(self, mock_request):
        """The message shape requests really produces, reproduced offline.

        Transcribed from an actual failed ``requests.get`` to this URL rather
        than invented -- note the credential appears as a bare *path*, with no
        scheme, which is what makes it invisible to any masking that expects to
        parse a whole URL. Built here instead of by calling out, so the test
        neither needs the network nor passes vacuously when there isn't any.
        """
        mock_request.side_effect = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='api.telegram.org', port=443): "
            f"Max retries exceeded with url: /file/bot123456:{self.TOKEN}"
            "/photo.jpg (Caused by NewConnectionError('failed to establish'))"
        )
        self.assertIn(
            self.TOKEN,
            str(mock_request.side_effect),
            "the fixture must actually carry the token, or this proves nothing",
        )

        with self.assertRaises(CommError) as caught:
            self._client().get(self.URL)

        self.assertNotIn(self.TOKEN, str(caught.exception))
        log = self._last_log()
        self.assertTrue(log, "the failure must still be recorded")
        self.assertNotIn(self.TOKEN, log.error_message or "")
        self.assertNotIn(self.TOKEN, log.request_url or "")

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_timeout_does_not_store_the_token(self, mock_request):
        mock_request.side_effect = requests.exceptions.ReadTimeout(
            f"HTTPSConnectionPool: Read timed out for url: {self.URL}"
        )

        with self.assertRaises(CommError) as caught:
            self._client().get(self.URL)

        self.assertNotIn(self.TOKEN, str(caught.exception))
        self.assertNotIn(self.TOKEN, self._last_log().error_message or "")

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_query_string_credential_is_masked_too(self, mock_request):
        """Not Telegram-specific: the same holds for a key in the query."""
        url = "https://example.invalid/live?api_key=SUPERSECRETKEY&page=2"
        mock_request.side_effect = requests.exceptions.ConnectionError(
            f"Max retries exceeded with url: {url}"
        )

        with self.assertRaises(CommError):
            self._client().get(url)

        log = self._last_log()
        self.assertNotIn("SUPERSECRETKEY", log.error_message or "")
        self.assertIn("page=2", log.error_message or "", "only the secret goes")


@tagged("post_install", "-at_install")
class TestExternalExchangeLogging(ClientLoggingCommon):
    """``log_external_exchange``: an exchange the client did not itself make.

    zeep drives its own SOAP envelopes over ``self.session``, so ``request``
    never sees them and everything inside it is bypassed. This is how such a
    caller puts the row back, and it must produce the same row a ``request``
    would — same redaction vocabulary, same schema — or the two paths drift and
    the one that drifts is the one that leaks.
    """

    def _queued(self):
        return self.env.cr.precommit.data.get("api.event.log.values") or []

    def test_it_records_a_successful_exchange(self):
        self._client().log_external_exchange(
            "POST", "https://pac.invalid/stamp", status_code=200, elapsed_ms=42
        )

        row = self._queued()[0]
        self.assertEqual(row["direction"], "outbound")
        self.assertEqual(row["status_code"], 200)
        self.assertEqual(row["state"], "success")
        self.assertEqual(row["duration_ms"], 42)

    def test_a_failure_is_recorded_as_failed(self):
        self._client().log_external_exchange(
            "POST", "https://pac.invalid/stamp", status_code=503, elapsed_ms=1
        )

        row = self._queued()[0]
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["error_type"], "server")

    def test_a_transport_error_with_no_status_is_a_network_failure(self):
        self._client().log_external_exchange(
            "POST", "https://pac.invalid/stamp", error="connection refused"
        )

        row = self._queued()[0]
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["error_type"], "network")

    def test_the_body_goes_through_the_same_redaction(self):
        """Not a parallel path: the same serializer, so the same guarantees."""
        self._client().log_external_exchange(
            "POST",
            "https://pac.invalid/stamp",
            request_body=json.dumps({"uuid": "abc-123", "password": SECRET_VALUE}),
            status_code=200,
        )

        payload = self._queued()[0]["request_payload"]
        self.assertIn("abc-123", payload)
        self.assertNotIn(SECRET_VALUE, payload)

    def test_a_credential_in_the_error_text_is_masked(self):
        """Error strings from another library carry whatever URL they were given."""
        self._client().log_external_exchange(
            "POST",
            "https://pac.invalid/stamp",
            error="failed calling https://pac.invalid/x?token=supersecrettoken",
        )

        self.assertNotIn("supersecrettoken", self._queued()[0]["error_message"])


@tagged("post_install", "-at_install")
class TestFailedExchangesAreRecordedAsFailed(ClientLoggingCommon):
    """``state`` follows the status, not whether anyone wrote a message.

    It used to be an unconditional "success" whenever a response came back, and
    only the presence of error *text* flipped it. ``_extract_error`` falls back
    to ``response.text``, so a 4xx/5xx with an empty body yields "" and the row
    recorded a failed exchange as successful -- while ``_track_usage`` counted
    the same call against the credential as a failure. A bodiless 502 from a
    proxy is the ordinary shape of this, and both SAT clients call with
    ``raise_for_status=False``, so they see the raw status.
    """

    def _last_log(self):
        self.env.cr.precommit.run()
        return self.env["api.event.log"].search([], order="id desc", limit=1)

    @staticmethod
    def _bodiless(status_code):
        response = MagicMock()
        response.status_code = status_code
        response.headers = {}
        response.text = ""
        response.json.side_effect = ValueError("no body")
        response.raise_for_status.return_value = None
        return response

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_bodiless_5xx_is_not_recorded_as_success(self, mock_request):
        mock_request.return_value = self._bodiless(502)

        result = self._client().get("/thing", raise_for_status=False)

        self.assertEqual(result["status_code"], 502)
        log = self._last_log()
        self.assertEqual(log.state, "failed")
        self.assertEqual(log.status_code, 502)
        self.assertEqual(log.error_type, "server", "failed rows need a kind too")

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_bodiless_4xx_is_classified_by_status(self, mock_request):
        mock_request.return_value = self._bodiless(429)

        self._client().get("/thing", raise_for_status=False)

        log = self._last_log()
        self.assertEqual(log.state, "failed")
        self.assertEqual(log.error_type, "rate_limit")

    @mute_logger("odoo.addons.api_transport.tools.api_client")
    @patch("requests.Session.request")
    def test_a_2xx_is_still_a_success(self, mock_request):
        """The guard against fixing this by calling everything failed."""
        mock_request.return_value = _ok_response()

        self._client().get("/thing", raise_for_status=False)

        log = self._last_log()
        self.assertEqual(log.state, "success")
        self.assertFalse(log.error_type)


@tagged("post_install", "-at_install")
class TestDigestAuthAndTlsVerification(TransactionCase):
    """Auth that needs a challenge, and where verification may be turned off.

    Digest cannot be a header: the server replies 401 with a nonce and the
    client hashes the credential against it. So it is the one auth type that
    has to reach requests as an ``auth`` object rather than through
    ``get_auth_headers``.

    TLS verification is a paired concern because the endpoint that needs digest
    here is the one that also cannot present a verifiable certificate -- a
    Hikvision access-control panel on a LAN, self-signed by construction.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.credential = cls.env["credential.credential"].create(
            {
                "name": "Device operator",
                "category_id": cls.env.ref(
                    "base_credential_manager.credential_category_basic_auth"
                ).id,
                "username": "admin",
                "password": "device-pass",
            }
        )

    def _service(self, **overrides):
        vals = {
            "name": "Device probe",
            "code": "device_probe",
            "endpoint_url": "https://192.168.1.50",
            "auth_type": "digest",
            "environment": "production",
            **overrides,
        }
        service = self.env["api.endpoint.outbound"].create(vals)
        self.credential.service_id = service
        return service

    def test_digest_auth_reaches_requests_as_a_challenge_handler(self):
        """Not a header: a tuple would silently do basic auth instead."""
        client = self._service()._get_api_client()

        self.assertIsInstance(client._get_auth(), HTTPDigestAuth)

    def test_a_non_digest_service_is_unaffected(self):
        """The pre-existing basic-auth pair, unchanged."""
        client = self._service(code="basic_probe", auth_type="basic")._get_api_client()

        self.assertEqual(client._get_auth(), ("admin", "device-pass"))

    def test_verification_stays_on_by_default(self):
        self.assertTrue(self._service(code="default_probe").verify_tls)

    def test_verification_may_be_disabled_for_a_private_host(self):
        service = self._service(code="lan_probe", verify_tls=False)

        self.assertFalse(
            service._get_api_client()._get_tls_verification(
                "https://192.168.1.50/ISAPI/System/deviceInfo"
            )
        )

    def test_verification_may_not_be_disabled_for_a_public_host(self):
        """The setting flipped once while debugging and never flipped back."""
        with self.assertRaises(ValidationError):
            self._service(
                code="public_probe",
                endpoint_url="https://api.example.com",
                verify_tls=False,
            )

    def test_a_public_host_is_refused_at_request_time_too(self):
        """The record's URL is a placeholder when callers pass absolute ones.

        The constraint can only ever inspect the placeholder, so the guard has
        to run again where the real host is known.
        """
        client = self._service(code="lan_probe2", verify_tls=False)._get_api_client()

        # UserError, not CommError: nothing was sent, and a caller wrapping
        # CommError would otherwise report this as "cannot connect".
        with self.assertRaises(UserError):
            client._get_tls_verification("https://api.example.com/v1/things")
