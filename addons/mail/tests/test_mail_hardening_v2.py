"""Regression tests for the second mail hardening audit.

Each test pins a specific bug found in the audit so a future refactor cannot
silently reintroduce it. Kept backend-only (no browser) for fast, deterministic
runs; the crypto helper is exercised as a pure unit.
"""

import email
import os

from odoo.tests.common import tagged

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.mail.tools import jwt as jwt_tool
from odoo.addons.mail.tools.web_push import _iv


@tagged("post_install", "-at_install")
class TestMailHardeningV2(MailCommon):
    def test_guest_token_non_numeric_id_no_crash(self):
        """A malformed ``dgid`` cookie must not 500 every public route.

        The id segment is attacker-controlled; a non-numeric value used to hit
        an unguarded ``int(...)`` and raise ValueError on essentially every
        public discuss/RTC route.
        """
        Guest = self.env["mail.guest"]
        # non-numeric id -> empty recordset, not ValueError
        self.assertFalse(Guest._get_guest_from_token("not-a-number|whatever"))
        # empty id segment
        self.assertFalse(Guest._get_guest_from_token("|whatever"))
        # well-formed but non-existent id -> empty, still no crash
        self.assertFalse(Guest._get_guest_from_token("999999999|whatever"))
        # a real guest with the wrong access token is rejected (no crash)
        guest = Guest.create({"name": "Regression Guest"})
        token = f"{guest.id}{Guest._cookie_separator}wrong-token"
        self.assertFalse(Guest._get_guest_from_token(token))
        # a real guest with the right token resolves
        good = f"{guest.id}{Guest._cookie_separator}{guest.sudo().access_token}"
        self.assertEqual(Guest._get_guest_from_token(good), guest)

    def test_rtc_session_batched_multi_channel_create(self):
        """Creating RTC sessions across >1 channel in one ``create`` must give
        every channel its "call started" side effects and return every session.

        A leaked loop variable used to leave all but the last channel without a
        call-history record and truncate the returned recordset.
        """
        channels = self.env["discuss.channel"]
        members = self.env["discuss.channel.member"]
        for idx in range(2):
            channel = self.env["discuss.channel"]._create_channel(
                name=f"RTC batch {idx}",
                group_id=self.env.ref("base.group_user").id,
            )
            channels += channel
            members += channel.sudo().channel_member_ids.filtered(
                lambda m: m.partner_id == self.env.user.partner_id
            )

        sessions = self.env["discuss.channel.rtc.session"].create(
            [{"channel_member_id": member.id} for member in members]
        )

        # the returned recordset spans BOTH channels, not just the last one
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions.channel_id, channels)
        # every channel got its own call-history record (the side effect that
        # the leaked loop variable used to drop for all but the last channel)
        history = self.env["discuss.call.history"].search(
            [("channel_id", "in", channels.ids)]
        )
        self.assertEqual(history.channel_id, channels)

    def test_followers_invalidate_documents_drops_cache(self):
        """``_invalidate_documents`` must actually evict the followed record's
        cache; it previously built the map and discarded it (a no-op)."""
        partner = self.env["res.partner"].create({"name": "Cache Subject"})
        # prime the ORM cache for a stored field
        partner.name  # noqa: B018
        self.assertTrue(self.env.cache.contains(partner, partner._fields["name"]))
        self.env["mail.followers"]._invalidate_documents(
            [{"res_model": partner._name, "res_id": partner.id}]
        )
        self.assertFalse(
            self.env.cache.contains(partner, partner._fields["name"]),
            "follower change must drop the followed record's cached fields",
        )

    def test_member_unread_counter_is_int_not_none(self):
        """A member with no unread messages reports ``0``, never ``None`` (the
        value is serialized to the client, which expects an integer)."""
        channel = self.env["discuss.channel"]._create_channel(
            name="Unread counter",
            group_id=self.env.ref("base.group_user").id,
        )
        member = channel.sudo().channel_member_ids.filtered(
            lambda m: m.partner_id == self.env.user.partner_id
        )
        member.invalidate_recordset(["message_unread_counter"])
        self.assertEqual(member.message_unread_counter, 0)
        self.assertIsInstance(member.message_unread_counter, int)

    def test_tracking_selection_unknown_new_value_no_crash(self):
        """Tracking a selection whose new value is no longer a declared option
        must fall back to the raw value instead of raising ``KeyError`` mid-write
        (old value was already defensive; new value was not)."""
        partner = self.env["res.partner"].create({"name": "Track Subject"})
        col_info = {
            "type": "selection",
            "selection": [("contact", "Contact")],  # 'delivery' intentionally absent
        }
        values = self.env["mail.tracking.value"]._create_tracking_values(
            "contact", "delivery", "type", col_info, partner
        )
        self.assertEqual(values["old_value_char"], "Contact")
        self.assertEqual(values["new_value_char"], "delivery")

    def test_web_push_iv_distinct_per_record(self):
        """RFC 8188 record nonces must differ per record (and the derivation
        helper, previously dead code, must stay wired in)."""
        base = os.urandom(12)
        ivs = [_iv(base, seq) for seq in range(4)]
        self.assertEqual(len(set(ivs)), len(ivs), "record nonces must be distinct")
        # first 4 bytes are the record-size prefix, unchanged across records
        self.assertTrue(all(iv[:4] == base[:4] for iv in ivs))

    def test_jwt_sign_no_side_effects(self):
        """``sign`` must not mutate the caller's claims dict, and must reject a
        zero ttl with an exception (not a bare ``assert`` stripped under -O)."""
        key = "c2VjcmV0LWtleS1mb3ItdGVzdGluZw"  # urlsafe base64, no padding
        claims = {"sub": "user-42"}
        token = jwt_tool.sign(claims, key, ttl=60, algorithm=jwt_tool.Algorithm.HS256)
        self.assertEqual(len(token.split(".")), 3, "well-formed JWT")
        self.assertNotIn("exp", claims, "caller's claims dict must be untouched")
        with self.assertRaises(ValueError):
            jwt_tool.sign(claims, key, ttl=0, algorithm=jwt_tool.Algorithm.HS256)

    def test_jwt_es256_sign_verifies_with_vapid_public_key(self):
        """An ES256-signed VAPID token must verify against the generated public
        key (the contract every push service checks): raw-key derivation and the
        r||s -> DSS signature encoding must round-trip."""
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        private_key, public_key = jwt_tool.generate_vapid_keys()
        token = jwt_tool.sign(
            {"aud": "https://push.test", "sub": "mailto:a@b.c"},
            private_key,
            ttl=12 * 60 * 60,
            algorithm=jwt_tool.Algorithm.ES256,
        )
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        raw_sig = jwt_tool.base64_decode_with_padding(sig_b64)
        self.assertEqual(len(raw_sig), 64, "P-256 signature is r||s, 32 bytes each")
        dss = utils.encode_dss_signature(
            int.from_bytes(raw_sig[:32], "big"), int.from_bytes(raw_sig[32:], "big")
        )
        pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), jwt_tool.base64_decode_with_padding(public_key)
        )
        # raises InvalidSignature on mismatch; no exception == verified
        pub.verify(dss, signing_input, ec.ECDSA(hashes.SHA256()))
        with self.assertRaises(InvalidSignature):
            pub.verify(dss, signing_input + b"tampered", ec.ECDSA(hashes.SHA256()))

    def test_detect_is_bounce_delivery_status_report(self):
        """A delivery-status report must be detected via the Content-Type
        ``report-type`` parameter, which ``get_content_type()`` strips."""
        thread = self.env["mail.thread"]
        dsn = email.message_from_string(
            "Content-Type: multipart/report; report-type=delivery-status\n\nbody"
        )
        self.assertTrue(
            thread._detect_is_bounce(
                dsn, {"to": "inbox@example.com", "email_from": "a@b.com"}
            )
        )
        plain = email.message_from_string("Content-Type: text/plain\n\nhi")
        self.assertFalse(
            thread._detect_is_bounce(
                plain, {"to": "inbox@example.com", "email_from": "a@b.com"}
            )
        )
        # the mailer-daemon localpart heuristic still fires
        self.assertTrue(
            thread._detect_is_bounce(
                plain, {"to": "inbox@example.com", "email_from": "MAILER-DAEMON@b.com"}
            )
        )
