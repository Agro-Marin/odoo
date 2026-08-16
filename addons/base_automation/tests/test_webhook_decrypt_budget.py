"""An authenticated webhook must not have a ceiling on how often it may be called.

`/web/hook/<uuid>` is `auth="public"`, so every sender in the world arrives as
one uid. While `_verify_webhook_request` read its secret through the ordinary
accessors, each call spent one of that credential's hourly decryptions against
that shared uid — measured 2026-08-14 as 100 x 200 followed by 30 x 422 for 130
correctly-signed POSTs, with 100 `read` and 30 `read_rate_limited` audit rows.

`credential.credential._get_verification_secret` reads the same secret without
the cap, on the ground that the caller is the server authenticating a request
rather than a person reading a credential.
"""

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestWebhookAuthDoesNotExhaustTheDecryptionCap(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.credential = cls.env["credential.credential"].create(
            {
                "name": "webhook decrypt-budget probe secret",
                "category_id": cls.env.ref(
                    "credential.credential_category_bearer_token"
                ).id,
                "credential_value": "HOOKSECRET",
            }
        )
        model = cls.env["ir.model"]._get("res.partner")
        action = cls.env["ir.actions.server"].create(
            {
                "name": "webhook budget probe action",
                "model_id": model.id,
                "state": "code",
                "code": "pass",
            }
        )
        cls.rule = cls.env["base.automation"].create(
            {
                "name": "webhook budget probe",
                "model_id": model.id,
                "trigger": "on_webhook",
                "action_server_ids": [(6, 0, action.ids)],
                "auth_type": "bearer",
                "credential_id": cls.credential.id,
                "rate_limit_enabled": False,
                "record_getter": "",
            }
        )

    def _fresh_request(self):
        """Drop every memo, so the next call decrypts as a new request would.

        Invalidating `cached_plaintext` alone is not enough: `credential_value`
        is computed FROM it and stays memoised, so the read never re-enters the
        capped choke point and the test passes against the unfixed code. In
        production every request is its own transaction and therefore its own
        decryption — which is why this only ever showed up over HTTP.
        """
        self.credential.invalidate_recordset()

    def _verify(self):
        return self.rule._verify_webhook_request(
            headers={"Authorization": "Bearer HOOKSECRET"},
            body=b'{"ping": 1}',
            remote_addr="10.0.0.1",
        )

    def test_a_low_cap_does_not_stop_the_webhook(self):
        # Three per hour: any per-request decryption would deny the fourth call.
        self.credential.sudo().write(
            {"enable_rate_limiting": True, "rate_limit_max_attempts": 3}
        )
        self.env.flush_all()

        for attempt in range(1, 26):
            self._fresh_request()
            ok, status, message = self._verify()
            self.assertTrue(
                ok,
                f"call {attempt} was refused ({status}: {message}); an "
                f"authenticated webhook must not have a per-hour ceiling",
            )

    def test_a_wrong_secret_is_still_refused(self):
        ok, status, _ = self.rule._verify_webhook_request(
            headers={"Authorization": "Bearer WRONG"},
            body=b'{"ping": 1}',
            remote_addr="10.0.0.1",
        )
        self.assertFalse(ok, "lifting the cap must not lift the authentication")
        self.assertEqual(status, 401)

    @mute_logger("odoo.addons.credential.models.credential_credential")
    def test_verification_writes_no_audit_rows(self):
        log = self.env["credential.access.log"].sudo()
        self.env.flush_all()
        before = log.search_count([("credential_id", "=", self.credential.id)])

        for _ in range(10):
            self._fresh_request()
            ok, _, _ = self._verify()
            self.assertTrue(ok)
        self.env.flush_all()

        self.assertEqual(
            log.search_count([("credential_id", "=", self.credential.id)]),
            before,
            "ten webhook deliveries used to leave ten 'read' rows describing "
            "traffic that was never suspicious",
        )

    def test_hmac_webhooks_are_covered_too(self):
        """HMAC is the case that genuinely cannot use a fingerprint."""
        import hashlib
        import hmac as hmac_mod

        self.rule.write(
            {
                "auth_type": "hmac_sha256",
                "signature_header": "X-Hub-Signature-256",
                "signature_prefix": "sha256=",
            }
        )
        self.credential.sudo().write(
            {"enable_rate_limiting": True, "rate_limit_max_attempts": 3}
        )
        self.env.flush_all()

        body = b'{"ping": 1}'
        digest = hmac_mod.new(b"HOOKSECRET", body, hashlib.sha256).hexdigest()
        for attempt in range(1, 16):
            self._fresh_request()
            ok, status, message = self.rule._verify_webhook_request(
                headers={"X-Hub-Signature-256": f"sha256={digest}"},
                body=body,
                remote_addr="10.0.0.1",
            )
            self.assertTrue(ok, f"HMAC call {attempt} refused ({status}: {message})")
