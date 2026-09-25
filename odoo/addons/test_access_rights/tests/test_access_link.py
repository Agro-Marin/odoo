from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.base.models.access_link import (
    LinkLoginRequired,
    LinkRefused,
    hash_token,
)


class AccessLinkCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = new_test_user(cls.env, "link_owner", groups="base.group_user")
        cls.stranger = new_test_user(cls.env, "link_stranger", groups="base.group_user")
        cls.portal = new_test_user(cls.env, "link_portal", groups="base.group_portal")
        cls.customer = cls.env["res.partner"].create({"name": "Link Customer"})
        cls.doc = (
            cls.env["test_access_right.shared_doc"]
            .with_user(cls.owner)
            .create({"name": "Quotation 7"})
        )
        cls.other = (
            cls.env["test_access_right.shared_doc"]
            .with_user(cls.owner)
            .create({"name": "Quotation 8"})
        )
        cls.Link = cls.env["access.link"]

    def _issue(self, record=None, **kwargs):
        record = (record or self.doc).with_user(self.owner)
        return self.Link.with_user(self.owner)._issue(record, **kwargs)


@tagged("post_install", "-at_install", "access_link")
class TestAccessLink(AccessLinkCase):
    def test_the_token_is_stored_as_its_hash_only(self):
        link, token = self._issue(partner=self.customer)
        self.env.cr.execute(
            "SELECT token_hash, token_nonce FROM access_link WHERE id = %s", [link.id]
        )
        stored_hash, nonce = self.env.cr.fetchone()
        self.assertEqual(stored_hash, hash_token(token))
        self.assertNotIn(token, (stored_hash, nonce))
        self.assertGreaterEqual(len(token), 32)

    def test_a_link_resolves_to_its_record(self):
        link, token = self._issue(partner=self.customer)
        resolution = self.Link.with_user(self.env.ref("base.public_user"))._resolve(
            token, model=self.doc._name, res_id=self.doc.id
        )
        self.assertEqual(resolution.record, self.doc)
        self.assertEqual(resolution.link, link)
        self.assertEqual(resolution.partner, self.customer)

    def test_every_refusal_is_the_same(self):
        _link, token = self._issue(partner=self.customer)
        public = self.Link.with_user(self.env.ref("base.public_user"))
        guessed = token[:-1] + ("A" if token[-1] != "A" else "B")
        doc = (self.doc._name, self.doc.id)
        refused = {
            "guessed": (guessed, *doc, "view"),
            "other record": (token, self.doc._name, self.other.id, "view"),
            "other model": (token, "res.partner", self.doc.id, "view"),
            "non-ascii": ("é" * 32, *doc, "view"),
            "too short": (token[:8], *doc, "view"),
            "not a string": (["x"] * 32, *doc, "view"),
            "higher role": (token, *doc, "edit"),
        }
        for label, (presented, model, res_id, role) in refused.items():
            with self.subTest(label), self.assertRaises(LinkRefused):
                public._resolve(presented, model=model, res_id=res_id, role=role)

    def test_revoked_and_expired_links_open_nothing(self):
        public = self.Link.with_user(self.env.ref("base.public_user"))
        revoked, revoked_token = self._issue(partner=self.customer)
        revoked.with_user(self.owner).action_revoke("sent to the wrong person")
        with self.assertRaises(LinkRefused):
            public._resolve(revoked_token)
        self.assertEqual(revoked.state, "revoked")

        expired, expired_token = self._issue(
            partner=self.env["res.partner"].create({"name": "Other"}),
            date_to=fields.Datetime.now() + timedelta(days=1),
        )
        public._resolve(expired_token)
        expired.sudo().date_to = fields.Datetime.now() - timedelta(seconds=1)
        with self.assertRaises(LinkRefused):
            public._resolve(expired_token)
        self.assertIn(expired, self.Link.sudo().search([("state", "=", "expired")]))

    def test_the_same_recipient_gets_the_same_link_back(self):
        first, token = self._issue(partner=self.customer, cause="notification")
        again, token_again = self._issue(partner=self.customer, cause="notification")
        self.assertEqual(first, again)
        self.assertEqual(token, token_again)
        other, other_token = self._issue(
            partner=self.env["res.partner"].create({"name": "Someone Else"}),
            cause="notification",
        )
        self.assertNotEqual(other, first)
        self.assertNotEqual(other_token, token)
        first.with_user(self.owner).action_revoke()
        fresh, fresh_token = self._issue(partner=self.customer, cause="notification")
        self.assertNotEqual(fresh, first)
        self.assertNotEqual(fresh_token, token)

    def test_a_link_anyone_can_use_expires_by_its_purpose(self):
        now = fields.Datetime.now()
        shared, _token = self._issue(cause="share")
        self.assertAlmostEqual(
            shared.date_to, now + timedelta(days=30), delta=timedelta(minutes=5)
        )
        sent, _token = self._issue(partner=self.customer, cause="notification")
        self.assertAlmostEqual(
            sent.date_to, now + timedelta(days=365), delta=timedelta(minutes=5)
        )

    def test_only_an_administrator_waives_the_expiry(self):
        with self.assertRaises(AccessError):
            self._issue(waive_expiry=True)
        admin = self.env.ref("base.user_admin")
        self.doc.sudo().reader_ids = admin
        link, _token = self.Link.with_user(admin)._issue(
            self.doc.with_user(admin), waive_expiry=True
        )
        self.assertFalse(link.date_to)
        self.assertTrue(link.expiry_waived)

    def test_issuing_needs_the_right_the_link_hands_out(self):
        with self.assertRaises(AccessError):
            self.Link.with_user(self.stranger)._issue(self.doc.with_user(self.stranger))
        self.env["test_access_right.shared_doc"].browse(
            self.doc.id
        ).sudo().reader_ids = self.stranger
        self.Link.with_user(self.stranger)._issue(self.doc.with_user(self.stranger))
        with self.assertRaises(AccessError):
            self.Link.with_user(self.stranger)._issue(
                self.doc.with_user(self.stranger), role="edit"
            )

    def test_code_holding_the_manage_privilege_vouches_for_the_record(self):
        company = self.env["res.company"].create({"name": "Link Co"})
        self.doc.sudo().company_id = company
        stranger_links = self.Link.with_user(self.stranger)
        with self.assertRaises(AccessError):
            stranger_links._issue(self.doc.with_user(self.stranger))
        vouched = stranger_links.with_privilege(
            "base.privilege_manage_links", reason="a folder reached its subtree"
        )
        link, _token = vouched._issue(self.doc.with_user(self.stranger))
        self.assertEqual(link.sudo().company_id, company)
        vouched._update_record_links(
            self.doc.with_user(self.stranger), {"role": "edit"}
        )
        vouched._revoke_record_links(self.doc.with_user(self.stranger), "moved")
        self.assertEqual(link.sudo().state, "revoked")

    def test_nobody_picks_a_token_or_a_record(self):
        link, _token = self._issue()
        chosen = {
            "token_hash": hash_token("A" * 32),
            "res_id": self.other.id,
            "revoked_at": False,
            "use_count": 0,
        }
        for field_name, value in chosen.items():
            with self.subTest(field_name), self.assertRaises(AccessError):
                link.with_user(self.env.ref("base.user_admin")).write(
                    {field_name: value}
                )
        with self.assertRaises(AccessError):
            self.Link.with_user(self.env.ref("base.user_admin")).create(
                {
                    "res_model": self.doc._name,
                    "res_id": self.doc.id,
                    "token_hash": hash_token("A" * 32),
                }
            )
        with self.assertRaises(UserError):
            link.with_user(self.env.ref("base.user_admin")).unlink()

    def test_only_the_sharer_or_an_administrator_revokes(self):
        link, _token = self._issue()
        with self.assertRaises(AccessError):
            link.with_user(self.stranger).action_revoke()
        link.with_user(self.owner).action_revoke()
        self.assertEqual(link.revoked_by_id, self.owner)

        other, _token = self._issue(partner=self.customer)
        admin = self.env.ref("base.user_admin")
        other.with_user(admin).action_revoke("left the company")
        self.assertEqual(other.revoked_by_id, admin)

    def test_a_record_writer_revokes_every_link_of_the_record(self):
        first, _token = self._issue(partner=self.customer)
        second, _token = self._issue()
        self.doc.sudo().reader_ids = self.stranger
        with self.assertRaises(AccessError):
            self.Link.with_user(self.stranger)._revoke_record_links(
                self.doc.with_user(self.stranger), "not theirs"
            )
        self.Link.with_user(self.owner)._revoke_record_links(
            self.doc.with_user(self.owner), "the quotation was cancelled"
        )
        self.assertEqual((first | second).mapped("state"), ["revoked", "revoked"])

    def test_a_record_writer_changes_role_and_expiry_and_the_url_stays(self):
        link, token = self._issue(partner=self.customer)
        self.doc.sudo().reader_ids = self.stranger
        later = fields.Datetime.now() + timedelta(days=90)
        with self.assertRaises(AccessError):
            self.Link.with_user(self.stranger)._update_record_links(
                self.doc.with_user(self.stranger), {"role": "edit"}
            )
        with self.assertRaises(UserError):
            self.Link.with_user(self.owner)._update_record_links(
                self.doc.with_user(self.owner), {"token_hash": "x"}
            )
        self.Link.with_user(self.owner)._update_record_links(
            self.doc.with_user(self.owner), {"role": "edit", "date_to": later}
        )
        resolution = self.Link.with_user(self.env.ref("base.public_user"))._resolve(
            token, role="edit"
        )
        self.assertEqual(resolution.link, link)
        self.assertEqual(link.date_to, later.replace(microsecond=0))
        self.assertEqual(
            self.Link.with_user(self.stranger)._record_links(
                self.doc.with_user(self.stranger)
            ),
            link,
        )

    def test_the_audience_is_checked_against_the_session(self):
        partners_link, partners_token = self._issue(
            partner=self.portal.partner_id, audience="partners"
        )
        with self.assertRaises(LinkLoginRequired):
            self.Link.with_user(self.env.ref("base.public_user"))._resolve(
                partners_token
            )
        with self.assertRaises(LinkRefused):
            self.Link.with_user(self.stranger)._resolve(partners_token)
        resolution = self.Link.with_user(self.portal)._resolve(partners_token)
        self.assertEqual(resolution.link, partners_link)

        _signed, signed_token = self._issue(audience="signed_in")
        with self.assertRaises(LinkLoginRequired):
            self.Link.with_user(self.env.ref("base.public_user"))._resolve(signed_token)
        self.Link.with_user(self.stranger)._resolve(signed_token)

    def test_uses_are_counted_by_hour_address_user_and_action(self):
        link, token = self._issue(partner=self.customer)
        public = self.Link.with_user(self.env.ref("base.public_user"))
        with patch.object(
            type(self.env["ir.http"]),
            "_get_request_remote_addr",
            lambda self: "10.0.0.7",
        ):
            for _ in range(3):
                public._resolve(token)
            public._resolve(token, action="download")
            self.Link.with_user(self.portal)._resolve(token)
        link.invalidate_recordset()
        self.assertEqual(link.use_count, 5)
        self.assertTrue(link.last_used_at)
        rows = {(use.action, use.user_id): use.count for use in link.sudo().use_ids}
        public_id = 0
        self.assertEqual(
            rows,
            {
                ("view", public_id): 3,
                ("download", public_id): 1,
                ("view", self.portal.id): 1,
            },
        )

    def test_revoking_and_extending_are_logged(self):
        link, _token = self._issue()
        link.with_user(self.owner).action_extend(
            fields.Datetime.now() + timedelta(days=90)
        )
        link.with_user(self.owner).action_revoke("done")
        events = (
            self.env["ir.access.log"]
            .sudo()
            .search([("link_id", "=", link.id)])
            .mapped("event")
        )
        self.assertEqual(
            sorted(events), ["link_created", "link_extended", "link_revoked"]
        )

    def test_a_changed_secret_leaves_old_links_working(self):
        link, token = self._issue(partner=self.customer)
        self.env["ir.config_parameter"].sudo().set_param(
            "database.secret", "rotated-for-the-test"
        )
        public = self.Link.with_user(self.env.ref("base.public_user"))
        self.assertEqual(public._resolve(token).link, link)
        self.assertIsNone(link._token())
        fresh, fresh_token = self._issue(partner=self.customer)
        self.assertNotEqual(fresh, link)
        self.assertNotEqual(fresh_token, token)


@tagged("post_install", "-at_install", "access_link")
class TestLinkDoor(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = new_test_user(cls.env, "door_owner", groups="base.group_user")
        cls.stranger = new_test_user(
            cls.env, "door_stranger", password="door_stranger", groups="base.group_user"
        )
        cls.doc = (
            cls.env["test_access_right.shared_doc"]
            .with_user(cls.owner)
            .create({"name": "Invoice 12"})
        )
        cls.other = (
            cls.env["test_access_right.shared_doc"]
            .with_user(cls.owner)
            .create({"name": "Invoice 13"})
        )

    def _issue(self, **kwargs):
        return (
            self.env["access.link"]
            .with_user(self.owner)
            ._issue(self.doc.with_user(self.owner), **kwargs)
        )

    def test_the_door_opens_with_the_token_and_names_the_link(self):
        link, token = self._issue()
        res = self.url_open(
            f"/test_access_rights/shared/{self.doc.id}?access_token={token}"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"id": self.doc.id, "link": link.id})

    def test_the_door_refuses_every_bad_token_alike(self):
        _link, token = self._issue()
        for label, url in {
            "no token": f"/test_access_rights/shared/{self.doc.id}",
            "guessed": f"/test_access_rights/shared/{self.doc.id}?access_token={'A' * 32}",
            "other record": f"/test_access_rights/shared/{self.other.id}?access_token={token}",
            "role": f"/test_access_rights/shared_edit/{self.doc.id}?access_token={token}",
        }.items():
            with self.subTest(label):
                self.assertEqual(self.url_open(url).status_code, 404)

    def test_a_signed_in_reader_needs_no_token(self):
        self.authenticate("door_stranger", "door_stranger")
        self.assertEqual(
            self.url_open(f"/test_access_rights/shared/{self.doc.id}").status_code, 404
        )
        self.doc.sudo().reader_ids = self.stranger
        res = self.url_open(f"/test_access_rights/shared/{self.doc.id}")
        self.assertEqual(res.json(), {"id": self.doc.id, "link": False})

    def test_a_link_for_signed_in_people_sends_a_visitor_to_login(self):
        _link, token = self._issue(audience="signed_in")
        res = self.url_open(
            f"/test_access_rights/shared/{self.doc.id}?access_token={token}",
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 303)
        self.assertIn("/web/login", res.headers["Location"])
