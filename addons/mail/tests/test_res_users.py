from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from freezegun import freeze_time
from psycopg import IntegrityError

from odoo import Command
from odoo.exceptions import UserError
from odoo.http.geoip import GeoIP
from odoo.tests import RecordCapturer, tagged, users
from odoo.tools import mute_logger

from odoo.addons.base.models.res_users import ResUsersPatchedInTest
from odoo.addons.base.tests.common import HttpCaseWithUserDemo
from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user


@tagged("-at_install", "post_install", "mail_tools", "res_users")
class TestNotifySecurityUpdate(MailCommon):
    @users("employee")
    def test_security_update_email(self):
        with self.mock_mail_gateway():
            self.env.user.write({"email": "new@example.com"})

        self.assertSentEmail(
            '"YourTestCompany" <your.company@example.com>',
            ["e.e@example.com"],
            subject="Security Update: Email Changed",
        )

    @users("employee")
    def test_security_update_login(self):
        with self.mock_mail_gateway():
            self.env.user.write({"login": "newlogin"})

        self.assertSentEmail(
            '"YourTestCompany" <your.company@example.com>',
            [self.env.user.email_formatted],
            subject="Security Update: Login Changed",
        )

    def test_security_update_email_alerts_each_user_at_its_own_address(self):
        users = self.env["res.users"].create(
            [
                {
                    "login": "batch_email_%d" % idx,
                    "name": "Batch %d" % idx,
                    "email": "batch.%d@example.com" % idx,
                }
                for idx in range(3)
            ]
        )
        previous_emails = users.mapped("email")
        with self.mock_mail_gateway():
            users.write({"email": "shared.new@example.com"})

        alerts = self._new_mails.filtered(
            lambda mail: mail.subject == "Security Update: Email Changed"
        )
        self.assertEqual(len(alerts), 3, "one alert per user, not one per pair")
        self.assertEqual(sorted(alerts.mapped("email_to")), sorted(previous_emails))
        for alert, previous_email in zip(
            alerts.sorted("email_to"), sorted(previous_emails), strict=True
        ):
            self.assertIn(
                previous_email,
                alert.body_html,
                "the body must name the address the alert is sent to",
            )

    def test_security_update_email_cleared(self):
        user = mail_new_test_user(
            self.env,
            login="email_cleared",
            name="Email Cleared",
            email="cleared@example.com",
        )
        with self.mock_mail_gateway():
            user.write({"email": False})

        self.assertSentEmail(
            '"YourTestCompany" <your.company@example.com>',
            ["cleared@example.com"],
            subject="Security Update: Email Changed",
        )

    def test_security_update_silent_while_the_account_is_deleted(self):
        portal_user = mail_new_test_user(
            self.env,
            login="self_deleting",
            name="Self Deleting",
            email="self.deleting@example.com",
            groups="base.group_portal",
        )
        with self.mock_mail_gateway():
            portal_user._deactivate_portal_user()

        self.assertFalse(portal_user.active)
        self.assertFalse(
            self._new_mails.filtered(
                lambda mail: (mail.subject or "").startswith("Security Update")
            ),
            "no security alert is raised by the account-deletion rewrite",
        )

    def test_security_update_leaves_after_the_transaction_commits(self):
        user = mail_new_test_user(
            self.env, login="deferred_alert", name="Deferred", email="def@test.com"
        )
        MailMail = type(self.env["mail.mail"])
        with (
            patch.object(
                MailMail, "send_after_commit", autospec=True
            ) as send_after_commit,
            patch.object(MailMail, "send", autospec=True) as send_now,
        ):
            mails = user._notify_security_setting_update("Subject", "content")

        self.assertTrue(send_after_commit.called, "the send waits for the commit")
        self.assertFalse(send_now.called, "and never runs inside the transaction")
        self.assertTrue(mails.exists(), "the caller gets records that still exist")

    def test_security_update_prepare_values_reads_the_geoip_api(self):
        class _Record:
            class city:
                name = "Springfield"

            class country:
                name = "United States"
                iso_code = "US"

            class continent:
                name = None
                code = None

            subdivisions = [type("_Sub", (), {"name": "Illinois", "iso_code": "IL"})]

        geoip = GeoIP("8.8.8.8", None)
        vars(geoip)["_city_record"] = _Record()
        fake_request = MagicMock(geoip=geoip)
        fake_request.httprequest.remote_addr = "8.8.8.8"
        fake_request.httprequest.user_agent.browser = "firefox"
        fake_request.httprequest.user_agent.platform = "linux"

        with patch("odoo.addons.mail.models.res_users.request", fake_request):
            values = self.env.user._notify_security_setting_update_prepare_values(
                "content"
            )
        self.assertEqual(
            values["location_address"], "Near Springfield, Illinois, United States"
        )
        self.assertEqual(values["ip_address"], "8.8.8.8")
        self.assertEqual(values["browser"], "Firefox")
        self.assertEqual(values["useros"], "Linux")

        with (
            patch("odoo.addons.mail.models.res_users.request", fake_request),
            self.mock_mail_gateway(),
        ):
            self.env.user._notify_security_setting_update("Subject", "content")
        body = self._new_mails[-1].body_html
        self.assertIn("Springfield, Illinois, United States", body)
        self.assertIn("8.8.8.8", body)

    @users("employee")
    def test_security_update_password(self):
        with self.mock_mail_gateway():
            self.env.user.write({"password": "newpassword"})

        self.assertSentEmail(
            '"YourTestCompany" <your.company@example.com>',
            [self.env.user.email_formatted],
            subject="Security Update: Password Changed",
        )


@tagged("-at_install", "post_install", "mail_tools", "res_users")
class TestUser(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = cls._create_portal_user()

    @mute_logger("odoo.db")
    def test_notification_type_constraint(self):
        with self.assertRaises(
            IntegrityError, msg="Portal user can not receive notification in Odoo"
        ):
            mail_new_test_user(
                self.env,
                login="user_test_constraint_2",
                name="Test User 2",
                email="user_test_constraint_2@test.example.com",
                notification_type="inbox",
                groups="base.group_portal",
            )

    def test_notification_type_convert_internal_inbox_to_portal(self):
        user = mail_new_test_user(
            self.env,
            login="user_test_constraint_3",
            name="Test User 3",
            email="user_test_constraint_3@test.example.com",
            notification_type="inbox",
            groups="base.group_user",
        )

        self.assertEqual(user.notification_type, "inbox")
        self.assertIn(
            self.env.ref("mail.group_mail_notification_type_inbox"), user.group_ids
        )

        user.write(
            {
                "group_ids": [
                    (3, self.env.ref("base.group_user").id),
                    (4, self.env.ref("base.group_portal").id),
                ]
            }
        )
        self.assertEqual(user.notification_type, "email")
        self.assertNotIn(
            self.env.ref("mail.group_mail_notification_type_inbox"), user.group_ids
        )

        admin = mail_new_test_user(
            self.env,
            login="user_test_constraint_4",
            name="Test User 4",
            email="user_test_constraint_3@test.example.com",
            notification_type="inbox",
            groups="base.group_erp_manager",
        )
        admin.write(
            {
                "notification_type": "email",
                "group_ids": [
                    (3, self.env.ref("base.group_user").id),
                    (3, self.env.ref("base.group_erp_manager").id),
                    (4, self.env.ref("base.group_portal").id),
                ],
            }
        )
        self.assertFalse(admin._is_admin())
        self.assertTrue(admin._is_portal())
        self.assertEqual(admin.notification_type, "email")
        self.assertNotIn(
            self.env.ref("mail.group_mail_notification_type_inbox"), admin.group_ids
        )

    @freeze_time("2025-06-18 08:45:12")
    def test_has_out_of_office_configured_tracks_the_only_field_that_enables_it(self):
        Users = self.env["res.users"]
        self.env["res.users"].search([("out_of_office_from", "!=", False)]).write(
            {"out_of_office_from": False}
        )
        self.assertFalse(
            Users._has_out_of_office_configured(),
            "no user has an out-of-office window configured",
        )
        self.user_employee.write({"out_of_office_from": "2020-01-01 00:00:00"})
        self.assertTrue(
            Users._has_out_of_office_configured(),
            "write() must invalidate the cached flag, or the feature goes silent",
        )
        self.user_employee.write({"out_of_office_from": False})
        self.assertFalse(
            Users._has_out_of_office_configured(),
            "clearing it must invalidate the flag too",
        )
        created = mail_new_test_user(
            self.env,
            login="ooo_at_create",
            name="Out Of Office At Create",
            out_of_office_from="2020-01-01 00:00:00",
        )
        self.assertTrue(
            Users._has_out_of_office_configured(),
            "create() must invalidate the cached flag as well",
        )
        created.write({"out_of_office_from": False})
        self.assertFalse(Users._has_out_of_office_configured())

    def test_out_of_office(self):
        test_user = self.user_employee.with_user(self.user_employee)
        portal_user = self.portal_user
        now = datetime(2025, 6, 8, 8, 45, 12)
        for ooo_from, ooo_to, exp_ooo in [
            (False, False, False),
            (now - timedelta(hours=1), False, True),
            (False, now + timedelta(hours=1), False),
            (now - timedelta(hours=1), now + timedelta(hours=1), True),
            (now, now, True),
            (now - timedelta(hours=4), now - timedelta(hours=2), False),
            (now + timedelta(hours=2), now + timedelta(hours=4), False),
            (now + timedelta(hours=2), False, False),
        ]:
            with self.subTest(ooo_from=ooo_from, ooo_to=ooo_to):
                with self.mock_datetime_and_now(now):
                    test_user.write(
                        {
                            "out_of_office_from": ooo_from,
                            "out_of_office_to": ooo_to,
                        }
                    )
                    self.assertEqual(test_user.is_out_of_office, exp_ooo)

                    portal_user.write(
                        {
                            "out_of_office_from": ooo_from,
                            "out_of_office_to": ooo_to,
                        }
                    )
                    self.assertFalse(
                        portal_user.is_out_of_office, "Portal users are never OOO"
                    )

    def test_has_external_mail_server_reads_a_boolean(self):
        user = self.env.user
        icp = self.env["ir.config_parameter"].sudo()
        for stored, expected in (("False", False), ("True", True)):
            with self.subTest(stored=stored):
                icp.set_param("base_setup.default_external_email_server", stored)
                user.invalidate_recordset(["has_external_mail_server"])
                self.assertEqual(user.has_external_mail_server, expected)
        icp.search([("key", "=", "base_setup.default_external_email_server")]).unlink()
        user.invalidate_recordset(["has_external_mail_server"])
        self.assertFalse(
            user.has_external_mail_server, "unset means no external mail server"
        )

    def test_outgoing_mail_server_matches_the_normalized_address(self):
        user = mail_new_test_user(
            self.env,
            login="mixed_case_email",
            name="Mixed Case",
            email="Mixed.Case@Example.COM",
        )
        server = (
            self.env["ir.mail_server"]
            .sudo()
            .create(
                {
                    "name": "Mixed Case personal server",
                    "smtp_host": "smtp.example.com",
                    "smtp_user": user.email_normalized,
                    "from_filter": user.email_normalized,
                    "owner_user_id": user.id,
                }
            )
        )
        user.invalidate_recordset(["outgoing_mail_server_id"])
        self.assertEqual(user.outgoing_mail_server_id, server)

        self.env["res.users"]._gc_personal_mail_servers()
        self.assertTrue(server.exists(), "the autovacuum must not reap a live server")

    def test_outgoing_mail_server_reads_from_filter_like_the_sender_does(self):
        user = mail_new_test_user(
            self.env,
            login="from_filter_shapes",
            name="From Filter",
            email="From.Filter@Example.COM",
        )
        address = user.email_normalized
        server = (
            self.env["ir.mail_server"]
            .sudo()
            .create(
                {
                    "name": "From filter shapes",
                    "smtp_host": "smtp.example.com",
                    "smtp_user": address,
                    "from_filter": address,
                    "owner_user_id": user.id,
                }
            )
        )
        for from_filter, expected in (
            (address, True),
            (address.upper(), True),
            ("  %s  " % address, True),
            ("%s, other@example.com" % address, True),
            ("someone.else@example.com", False),
            (address.split("@")[1], False),
        ):
            with self.subTest(from_filter=from_filter):
                server.from_filter = from_filter
                user.invalidate_recordset(["outgoing_mail_server_id"])
                self.assertEqual(bool(user.outgoing_mail_server_id), expected)
                if expected:
                    self.assertTrue(
                        self.env["ir.mail_server"]._match_from_filter(
                            address, from_filter
                        ),
                        "the sender accepts it, so the compute must too",
                    )

    def test_outgoing_mail_server_ignores_another_users_server(self):
        user = mail_new_test_user(
            self.env, login="no_server", name="No Server", email="no.server@test.com"
        )
        other = mail_new_test_user(
            self.env, login="has_server", name="Has Server", email="has@test.com"
        )
        self.env["ir.mail_server"].sudo().create(
            {
                "name": "Other personal server",
                "smtp_host": "smtp.example.com",
                "smtp_user": other.email_normalized,
                "from_filter": other.email_normalized,
                "owner_user_id": other.id,
            }
        )
        (user + other).invalidate_recordset(["outgoing_mail_server_id"])
        self.assertFalse(user.outgoing_mail_server_id)
        self.assertEqual(user.outgoing_mail_server_type, "default")
        self.assertTrue(other.outgoing_mail_server_id)

    def test_personal_mail_server_survives_its_own_setup(self):
        user = mail_new_test_user(
            self.env, login="pending_oauth", name="Pending", email="pending@test.com"
        )
        pending = (
            self.env["ir.mail_server"]
            .sudo()
            .create(
                {
                    "active": False,
                    "name": "Pending setup",
                    "smtp_host": "smtp.example.com",
                    "smtp_user": user.email_normalized,
                    "from_filter": user.email_normalized,
                    "owner_user_id": user.id,
                }
            )
        )
        self.env["res.users"]._gc_personal_mail_servers()
        self.assertTrue(pending.exists(), "a setup in flight is not garbage")

        grace = self.env["ir.mail_server"]._get_personal_mail_server_grace()
        self.env.cr.execute(
            "UPDATE ir_mail_server SET create_date = %s WHERE id = %s",
            [self.env.cr.now() - timedelta(minutes=grace + 1), pending.id],
        )
        pending.invalidate_recordset(["create_date"])
        self.env["res.users"]._gc_personal_mail_servers()
        self.assertFalse(pending.exists(), "an abandoned setup is collected")

    def test_personal_mail_server_is_collected_when_unused(self):
        user = mail_new_test_user(
            self.env, login="stale_server", name="Stale", email="stale@test.com"
        )
        server = (
            self.env["ir.mail_server"]
            .sudo()
            .create(
                {
                    "name": "Stale server",
                    "smtp_host": "smtp.example.com",
                    "smtp_user": user.email_normalized,
                    "from_filter": user.email_normalized,
                    "owner_user_id": user.id,
                }
            )
        )
        self.env["res.users"]._gc_personal_mail_servers()
        self.assertTrue(server.exists())

        user.write({"email": "moved.on@test.com"})
        self.env["res.users"]._gc_personal_mail_servers()
        self.assertFalse(
            server.exists(), "the owner's address moved on; the server has not"
        )

    def test_out_of_office_flag_is_cleared_when_its_last_user_goes(self):
        Users = self.env["res.users"]
        Users.search([("out_of_office_from", "!=", False)]).write(
            {"out_of_office_from": False}
        )
        user = mail_new_test_user(
            self.env,
            login="ooo_unlinked",
            name="OOO Unlinked",
            email="ooo.unlinked@test.com",
            out_of_office_from="2020-01-01 00:00:00",
        )
        self.assertTrue(Users._has_out_of_office_configured())
        user.unlink()
        self.assertFalse(
            Users._has_out_of_office_configured(),
            "unlink must invalidate the flag like create and write do",
        )

    def test_im_status_without_a_presence(self):
        user = mail_new_test_user(
            self.env, login="no_presence", name="No Presence", email="np@test.com"
        )
        self.assertFalse(user.presence_ids)
        self.assertEqual(user.im_status, "offline")
        self.assertEqual(user.partner_id.im_status, "offline")

    def test_im_status_is_resolved_the_same_way_for_user_and_partner(self):
        user = mail_new_test_user(
            self.env, login="with_presence", name="Presence", email="wp@test.com"
        )
        presence = self.env["mail.presence"].create({"user_id": user.id})
        for status, manual, expected in (
            ("online", False, "online"),
            ("online", "busy", "busy"),
            ("away", False, "away"),
            ("offline", "busy", "offline"),
        ):
            with self.subTest(status=status, manual=manual):
                presence.status = status
                user.manual_im_status = manual
                user.invalidate_recordset(["im_status"])
                user.partner_id.invalidate_recordset(["im_status"])
                self.assertEqual(user.im_status, expected)
                self.assertEqual(user.partner_id.im_status, expected)

    def test_deactivating_a_user_removes_their_activities(self):
        for archive in (
            lambda user: user.write({"active": False}),
            lambda user: user.action_archive(),
        ):
            with self.subTest(archive=archive):
                user = mail_new_test_user(
                    self.env,
                    login="to_archive_%s" % id(archive),
                    name="To Archive",
                    email="to.archive@test.com",
                )
                activity = self.env["mail.activity"].create(
                    {
                        "activity_type_id": self.env.ref(
                            "mail.mail_activity_data_todo"
                        ).id,
                        "res_id": self.partner_admin.id,
                        "res_model_id": self.env["ir.model"]._get_id("res.partner"),
                        "user_id": user.id,
                    }
                )
                archive(user)
                self.assertFalse(user.active)
                self.assertFalse(
                    activity.exists(),
                    "an archived user keeps no assigned activity",
                )

    def test_notification_type_follows_an_implied_inbox_group(self):
        inbox_group = self.env.ref("mail.group_mail_notification_type_inbox")
        implying_group = self.env["res.groups"].create(
            {"name": "Implies Inbox", "implied_ids": [Command.set(inbox_group.ids)]}
        )
        user = mail_new_test_user(
            self.env, login="implied_inbox", name="Implied", groups="base.group_user"
        )
        self.assertEqual(user.notification_type, "email")

        user.write({"group_ids": [Command.link(implying_group.id)]})
        self.assertIn(inbox_group, user.all_group_ids)
        self.assertNotIn(inbox_group, user.group_ids, "held only by implication")
        self.assertEqual(user.notification_type, "inbox")

        user.write({"group_ids": [Command.unlink(implying_group.id)]})
        self.assertNotIn(inbox_group, user.all_group_ids)
        self.assertEqual(user.notification_type, "email")

    def test_notification_type_is_computed_from_a_pre_flush_group_write(self):
        inbox_group = self.env.ref("mail.group_mail_notification_type_inbox")
        user = mail_new_test_user(
            self.env, login="direct_inbox", name="Direct", groups="base.group_user"
        )
        user.write({"group_ids": [Command.link(inbox_group.id)]})
        self.assertEqual(user.notification_type, "inbox")
        self.assertIn(inbox_group, user.group_ids, "the grant must survive")

    def test_portal_user_loses_the_inbox_group_outside_the_compute(self):
        user = mail_new_test_user(
            self.env,
            login="demoted_inbox",
            name="Demoted",
            notification_type="inbox",
            groups="base.group_user",
        )
        inbox_group = self.env.ref("mail.group_mail_notification_type_inbox")
        self.assertIn(inbox_group, user.group_ids)

        user.write(
            {
                "group_ids": [
                    Command.unlink(self.env.ref("base.group_user").id),
                    Command.link(self.env.ref("base.group_portal").id),
                ]
            }
        )
        self.assertTrue(user.share)
        self.assertEqual(user.notification_type, "email")
        self.assertNotIn(inbox_group, user.group_ids)

    def test_activity_systray_says_when_it_truncates(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "mail.activity.systray.limit", "1"
        )
        partners = self.env["res.partner"].create(
            [{"name": "Systray %d" % index} for index in range(2)]
        )
        self.env["mail.activity"].create(
            [
                {
                    "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                    "res_id": partner.id,
                    "res_model_id": self.env["ir.model"]._get_id("res.partner"),
                    "user_id": self.env.user.id,
                }
                for partner in partners
            ]
        )
        with self.assertLogs(
            "odoo.addons.mail.models.res_users", level="WARNING"
        ) as capture:
            groups = self.env["res.users"]._get_activity_groups()
        self.assertIn("undercounts", capture.output[0])
        self.assertEqual(sum(group["due_count"] for group in groups), 1)

    def test_web_create_users(self):
        src = [
            "POILUCHETTE@test.example.com",
            '"Jean Poilvache" <POILVACHE@test.example.com>',
        ]
        with self.mock_mail_gateway(), RecordCapturer(self.env["res.users"]) as capture:
            self.env["res.users"].web_create_users(src)

        exp_emails = ["poiluchette@test.example.com", "poilvache@test.example.com"]
        for user_email in exp_emails:
            self.assertSentEmail(
                self.env.company.partner_id.email_formatted,
                [user_email],
                email_from=self.env.company.partner_id.email_formatted,
            )

        self.assertEqual(len(capture.records), 2, "Should create one user / entry")
        self.assertEqual(
            sorted(capture.records.mapped("name")),
            sorted(("poiluchette@test.example.com", "Jean Poilvache")),
        )
        self.assertEqual(sorted(capture.records.mapped("email")), sorted(exp_emails))


@tagged("-at_install", "post_install", "mail_tools", "res_users", "mail_server")
class TestPersonalMailServerSetup(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "base_setup.default_external_email_server", "True"
        )
        cls.server_user = mail_new_test_user(
            cls.env,
            login="server_owner",
            name="Server Owner",
            email="server.owner@test.example.com",
            groups="base.group_user",
        )

    @contextmanager
    def _stub_setup_end_action(self):
        def end_action(self, smtp_server):
            return {"stub_server_id": smtp_server.id}

        with patch.object(
            type(self.env["res.users"]),
            "_get_mail_server_setup_end_action",
            end_action,
        ):
            yield

    def _setup(self, user, server_type):
        with self._stub_setup_end_action():
            return (
                self.env["res.users"]
                .with_user(user)
                .action_setup_outgoing_mail_server(server_type)
            )

    def _owned_server(self, user):
        return (
            self.env["ir.mail_server"]
            .sudo()
            .with_context(active_test=False)
            .search([("owner_user_id", "=", user.id)])
        )

    def test_setup_refuses_when_the_feature_is_off(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "base_setup.default_external_email_server", "False"
        )
        with self.assertRaises(UserError):
            self._setup(self.server_user, "default")

    def test_setup_refuses_a_portal_user(self):
        portal_user = self._create_portal_user()
        with self.assertRaises(UserError):
            self._setup(portal_user, "default")

    def test_setup_refuses_an_unknown_type(self):
        with self.assertRaises(UserError):
            self._setup(self.server_user, "not_a_server_type")

    def test_setup_refuses_an_address_it_cannot_own(self):
        for email, reason in (
            (False, "no address at all"),
            ("@test.example.com", "no local part"),
        ):
            with self.subTest(email=email):
                self.server_user.sudo().email = email
                with self.assertRaises(UserError, msg=reason):
                    self._setup(self.server_user, "gmail")
        self.server_user.sudo().email = "server.owner@test.example.com"

    def test_setup_refuses_an_address_owned_by_an_alias_domain(self):
        alias_domain = self.env["mail.alias.domain"].sudo().search([], limit=1)
        self.server_user.sudo().email = alias_domain.default_from_email
        with self.assertRaises(UserError):
            self._setup(self.server_user, "gmail")

    def test_setup_default_removes_the_personal_server(self):
        self.env["ir.mail_server"].sudo().create(self._server_vals(self.server_user))
        self.assertTrue(self._owned_server(self.server_user))

        action = self._setup(self.server_user, "default")

        self.assertFalse(self._owned_server(self.server_user))
        self.assertEqual(action["tag"], "display_notification")

    def test_setup_creates_an_inactive_server_for_the_owner(self):
        action = self._setup(self.server_user, "gmail")

        server = self._owned_server(self.server_user)
        self.assertEqual(action["stub_server_id"], server.id)
        self.assertFalse(server.active, "it is activated by the OAuth callback")
        self.assertEqual(server.owner_user_id, self.server_user)
        self.assertEqual(server.from_filter, self.server_user.email_normalized)
        self.assertEqual(server.smtp_user, self.server_user.email_normalized)
        self.assertEqual(server.smtp_port, 587)
        self.assertEqual(server.smtp_encryption, "starttls")
        self.assertEqual(server.smtp_host, "smtp.gmail.com")

    def test_setup_resumes_an_authorization_instead_of_replacing_it(self):
        self._setup(self.server_user, "gmail")
        server = self._owned_server(self.server_user)
        server.write({"active": True, "from_filter": server.from_filter.upper()})
        self.server_user.invalidate_recordset(
            ["outgoing_mail_server_id", "outgoing_mail_server_type"]
        )

        action = self._setup(self.server_user, "gmail")

        self.assertEqual(
            action["stub_server_id"], server.id, "the same server, still authorized"
        )
        self.assertTrue(server.exists())
        self.assertEqual(self._owned_server(self.server_user), server)

    def _server_vals(self, user):
        return {
            "name": "Owned by %s" % user.name,
            "smtp_host": "smtp.example.com",
            "smtp_user": user.email_normalized,
            "from_filter": user.email_normalized,
            "owner_user_id": user.id,
        }


@tagged("-at_install", "post_install", "res_users")
class TestUserTours(HttpCaseWithUserDemo):
    def test_user_modify_own_profile(self):
        if "hr.employee" in self.env and not self.user_demo.employee_id:
            self.env["hr.employee"].create(
                {
                    "name": "Marc Demo",
                    "user_id": self.user_demo.id,
                }
            )
            self.user_demo.group_ids += self.env.ref("hr.group_hr_user")
        self.user_demo.tz = "Europe/Brussels"
        self.user_demo.notification_type = "email"

        with patch.object(ResUsersPatchedInTest, "preference_save", lambda self: True):
            self.start_tour(
                "/odoo",
                "mail/static/tests/tours/user_modify_own_profile_tour.js",
                login="demo",
            )
        self.assertEqual(self.user_demo.notification_type, "inbox")


@tagged("post_install", "-at_install")
class TestUserSettings(MailCommon):
    def test_create_portal_user(self):
        portal_group = self.env.ref("base.group_portal")
        user = self.env.user.create(
            {
                "name": "A portal user",
                "login": "portal_test",
                "group_ids": [(6, 0, [portal_group.id])],
            }
        )
        self.assertFalse(
            user.res_users_settings_ids,
            "Portal users should not have settings by default",
        )

    def test_create_internal_user(self):
        user = self.env.user.create(
            {
                "name": "A internal user",
                "login": "test_user",
            }
        )
        self.assertTrue(
            user.res_users_settings_ids,
            "Internal users should have settings by default",
        )

    @users("employee")
    def test_find_or_create_for_user_should_create_record_if_not_existing(self):
        self.user_employee.res_users_settings_ids.unlink()
        settings = self.user_employee.res_users_settings_ids
        self.assertFalse(settings, "no records should exist")

        self.env["res.users.settings"]._get_or_create_for_user(self.user_employee)
        settings = self.user_employee.res_users_settings_ids
        self.assertTrue(
            settings,
            "a record should be created after _get_or_create_for_user is called",
        )

    @users("employee")
    def test_find_or_create_for_user_should_return_correct_res_users_settings(self):
        self.user_employee.res_users_settings_ids.unlink()
        settings = self.env["res.users.settings"].create(
            {
                "user_id": self.user_employee.id,
            }
        )
        result = self.env["res.users.settings"]._get_or_create_for_user(
            self.user_employee
        )
        self.assertEqual(
            result, settings, "Correct mail user settings should be returned"
        )

    @users("employee")
    def test_set_res_users_settings_should_send_notification_on_bus(self):
        settings = self.user_employee.res_users_settings_id
        settings.is_discuss_sidebar_category_chat_open = False
        settings.is_discuss_sidebar_category_channel_open = False

        with self.assertBus(
            [(self.cr.dbname, "res.partner", self.partner_employee.id)],
            [
                {
                    "type": "res.users.settings",
                    "payload": {
                        "id": settings.id,
                        "is_discuss_sidebar_category_chat_open": True,
                    },
                }
            ],
        ):
            settings.set_res_users_settings(
                {"is_discuss_sidebar_category_chat_open": True}
            )

    @users("employee")
    def test_set_res_users_settings_should_set_settings_properly(self):
        settings = self.user_employee.res_users_settings_id
        settings.set_res_users_settings({"is_discuss_sidebar_category_chat_open": True})
        self.assertEqual(
            settings.is_discuss_sidebar_category_chat_open,
            True,
            "category state should be updated correctly",
        )
