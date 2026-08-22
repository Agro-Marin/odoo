from odoo.http import Request
from odoo.tests.common import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.portal.controllers.portal import _pager_url, pager
from odoo.addons.portal.utils import (
    validate_thread_with_hash_pid,
    validate_thread_with_token,
)


class _FakeTokenThread:

    _mail_post_token_field = "access_token"
    _fields = {"access_token": object()}

    def __init__(self, token="a-real-token"):
        self._token = token

    def __getitem__(self, key):
        return self._token

    def _sign_token(self, pid):
        return "signature-for-%s" % pid

    def _portal_get_parent_hash_token(self, pid):
        return False


class TestCredentialTypeCoercion(TransactionCase):

    def test_hash_pid_non_str_hash(self):
        for bad_hash in (5, 5.5, True, ["deadbeef"], {"a": 1}):
            with self.subTest(hash=bad_hash):
                self.assertFalse(
                    validate_thread_with_hash_pid(_FakeTokenThread(), bad_hash, 1)
                )

    def test_hash_pid_non_numeric_pid(self):
        for bad_pid in (["1"], {"id": 1}, 1.5, object()):
            with self.subTest(pid=bad_pid):
                self.assertFalse(
                    validate_thread_with_hash_pid(
                        _FakeTokenThread(), "deadbeef", bad_pid
                    )
                )

    def test_hash_pid_happy_path_still_validates(self):
        thread = _FakeTokenThread()
        self.assertTrue(validate_thread_with_hash_pid(thread, thread._sign_token(7), 7))
        self.assertTrue(
            validate_thread_with_hash_pid(thread, thread._sign_token(7), "7")
        )

    def test_token_non_str(self):
        for bad_token in (5, ["a-real-token"], {"t": 1}, True):
            with self.subTest(token=bad_token):
                self.assertFalse(
                    validate_thread_with_token(_FakeTokenThread(), bad_token)
                )

    def test_token_happy_path_still_validates(self):
        self.assertTrue(validate_thread_with_token(_FakeTokenThread("tok"), "tok"))


class TestRecordPagerUrl(TransactionCase):

    def test_empty_url_field_yields_no_link(self):
        partner = self.env.ref("base.partner_root")

        class _NoUrlRecord:
            _fields = {"website_url": object()}

            def __init__(self, record):
                self._record = record

            def __getitem__(self, key):
                return ""

            def __bool__(self):
                return True

        self.assertFalse(_pager_url(_NoUrlRecord(partner), "website_url"))

    def test_missing_neighbour_yields_no_link(self):
        self.assertFalse(_pager_url(False, "access_url"))


@tagged("-at_install", "post_install")
class TestAddressBooleanParam(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = mail_new_test_user(
            cls.env,
            "portal_coercion",
            groups="base.group_portal",
            name="Portal Coercion",
        )

    def _login(self):
        self.authenticate("portal_coercion", "portal_coercion")

    @mute_logger("odoo.http")
    def test_address_form_junk_use_delivery_as_billing(self):
        self._login()
        for value in ("xyz", "2", " true", "True%20", "[]"):
            with self.subTest(value=value):
                response = self.url_open(f"/my/address?use_delivery_as_billing={value}")
                self.assertEqual(response.status_code, 200)

    @mute_logger("odoo.http")
    def test_address_submit_junk_use_delivery_as_billing(self):
        self._login()
        response = self.url_open(
            "/my/address/submit",
            data={
                "use_delivery_as_billing": "xyz",
                "name": "Portal Coercion",
                "email": "portal_coercion@example.com",
                "csrf_token": Request.csrf_token(self),
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_address_form_recognised_values_still_work(self):
        self._login()
        for value in ("True", "true", "1", "on"):
            with self.subTest(value=value):
                response = self.url_open(f"/my/address?use_delivery_as_billing={value}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    'name="use_delivery_as_billing" value="True"', response.text
                )


class TestShareRecipientSplit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.with_user = cls.env["res.partner"].create(
            {"name": "Has User", "email": "has_user@example.com"}
        )
        cls.env["res.users"].create(
            {
                "name": "Has User",
                "login": "share_split_has_user",
                "partner_id": cls.with_user.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
            }
        )
        cls.without_user = cls.env["res.partner"].create(
            {"name": "No User", "email": "no_user@example.com"}
        )

    def _wizard(self):
        return self.env["portal.share"].create(
            {
                "res_model": "res.partner",
                "res_id": self.with_user.id,
                "partner_ids": [(6, 0, (self.with_user | self.without_user).ids)],
            }
        )

    def _set_invitation_scope(self, scope):
        self.env["ir.config_parameter"].sudo().set_param(
            "auth_signup.invitation_scope", scope
        )

    def test_signup_open_splits_by_user_presence(self):
        self._set_invitation_scope("b2c")
        wizard = self._wizard()
        public = wizard._get_public_link_partners()
        self.assertEqual(public, self.with_user)
        self.assertEqual(wizard.partner_ids - public, self.without_user)

    def test_signup_closed_gives_everyone_the_public_link(self):
        self._set_invitation_scope("b2b")
        wizard = self._wizard()
        self.assertEqual(
            wizard._get_public_link_partners(), self.with_user | self.without_user
        )

    def test_split_is_independent_of_an_already_minted_token(self):
        self._set_invitation_scope("b2c")
        wizard = self._wizard()
        first = wizard._get_public_link_partners()
        second = self._wizard()._get_public_link_partners()
        self.assertEqual(first, second)
        self.assertNotIn(self.without_user, second)


class TestPortalMessageFormatScaling(TransactionCase):

    def _make_messages(self, count):
        thread = self.env["res.partner"].create({"name": "Chatter Scaling"})
        return self.env["mail.message"].concat(
            *[
                thread.message_post(
                    body=f"<p>m{i}</p>",
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
                for i in range(count)
            ]
        )

    def _queries_to_format(self, messages):
        self.env.flush_all()
        self.env.invalidate_all()
        cold = self.env["mail.message"].browse(messages.ids)
        before = self.env.cr.sql_log_count
        cold.portal_message_format(options={})
        return self.env.cr.sql_log_count - before

    def test_query_count_does_not_grow_with_message_count(self):
        few = self._make_messages(3)
        many = self._make_messages(30)
        cost_few = self._queries_to_format(few)
        cost_many = self._queries_to_format(many)
        self.assertLessEqual(
            cost_many,
            cost_few + 5,
            "formatting 10x the messages cost %s extra queries (was ~1 per "
            "message before the prefetch in _portal_message_format)"
            % (cost_many - cost_few),
        )


class TestPagerBounds(TransactionCase):

    def test_non_positive_step(self):
        for step in (0, -5):
            with self.subTest(step=step):
                values = pager("/my/orders", total=100, step=step)
                self.assertGreaterEqual(values["page_count"], 1)
                self.assertEqual(values["page"]["num"], 1)
                for page in values["pages"]:
                    if page["url"]:
                        self.assertNotIn("/page/-", page["url"])

    def test_negative_total(self):
        values = pager("/my/orders", total=-10)
        self.assertEqual(values["page_count"], 1)
        self.assertEqual(values["offset"], 0)

    def test_normal_paging_unchanged(self):
        values = pager("/my/orders", total=100, step=20)
        self.assertEqual(values["page_count"], 5)
        self.assertEqual(values["offset"], 0)
        self.assertEqual([p["num"] for p in values["pages"]], [1, 2, 3, 4, 5])

    def test_page_digit_lookalikes_fall_back_instead_of_raising(self):
        for page in ("²", "①", "⁵"):
            with self.subTest(page=page):
                self.assertTrue(page.isdigit(), "fixture must be an isdigit trap")
                values = pager("/my/orders", total=100, step=20, page=page)
                self.assertEqual(values["page"]["num"], 1)

    def test_page_non_ascii_decimal_digits_still_parse(self):
        values = pager("/my/orders", total=100, step=20, page="٣")
        self.assertEqual(values["page"]["num"], 3)

    def test_page_junk_falls_back_to_first_page(self):
        for page in ("abc", "", "-3", "2.5", None):
            with self.subTest(page=page):
                values = pager("/my/orders", total=100, step=20, page=page)
                self.assertEqual(values["page"]["num"], 1)


@tagged("-at_install", "post_install")
class TestPortalApiKeysVisibility(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = mail_new_test_user(
            cls.env, "portal_keys", groups="base.group_portal", name="Portal Keys"
        )

    def _security_page(self):
        self.authenticate("portal_keys", "portal_keys")
        return self.url_open("/my/security").text

    def test_section_hidden_when_setting_off(self):
        self.env["ir.config_parameter"].sudo().set_param("portal.allow_api_keys", "")
        self.assertNotIn("o_portal_new_api_key", self._security_page())

    def test_section_shown_when_setting_on_without_debug(self):
        self.env["ir.config_parameter"].sudo().set_param("portal.allow_api_keys", "1")
        self.assertIn("o_portal_new_api_key", self._security_page())
