from contextlib import contextmanager
from unittest.mock import Mock, patch

from odoo import Command
from odoo.tests.common import HttpCase, TransactionCase, new_test_user
from odoo.tools.mail import email_split_and_format

DISABLED_MAIL_CONTEXT = {
    "tracking_disable": True,
    "mail_create_nolog": True,
    "mail_create_nosubscribe": True,
    "mail_notrack": True,
    "no_reset_password": True,
}


class BaseCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env = cls.env["base"].with_context(**cls.default_env_context()).env

        independent_user = cls.setup_independent_user()
        if independent_user:
            cls.env = cls.env(user=independent_user)
            cls.user = cls.env.user
        else:
            cls.env.user.group_ids += cls.get_default_groups()

        independent_company = cls.setup_independent_company()
        if independent_company:
            cls.env.user.company_id = independent_company
            cls.env.user.company_ids = [Command.set(independent_company.ids)]
        else:
            cls.setup_main_company()

        cls.company = cls.env.company
        cls.currency = cls.env.company.currency_id

        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test Partner",
            }
        )

        cls.group_portal = cls.quick_ref("base.group_portal")
        cls.group_user = cls.quick_ref("base.group_user")
        cls.group_system = cls.quick_ref("base.group_system")

    @classmethod
    def default_env_context(cls):
        return {**DISABLED_MAIL_CONTEXT}

    @classmethod
    def setup_other_currency(cls, code, **kwargs):
        rates = kwargs.pop("rates", [])
        currency = cls._enable_currency(code)
        currency.rate_ids.unlink()
        currency.write(
            {
                "active": True,
                "rate_ids": [
                    Command.create(
                        {
                            "name": rate_date,
                            "rate": rate,
                            "company_id": cls.env.company.id,
                        }
                    )
                    for rate_date, rate in rates
                ],
                **kwargs,
            }
        )
        return currency

    @classmethod
    def setup_independent_company(cls, **kwargs):
        return None

    @classmethod
    def setup_independent_user(cls):
        return None

    @classmethod
    def get_default_groups(cls):
        return cls.env.ref("base.group_user")

    @classmethod
    def setup_main_company(cls, currency_code="USD"):
        cls._use_currency(cls.env.company, currency_code)

    @classmethod
    def _enable_currency(cls, currency_code):
        currency = (
            cls.env["res.currency"]
            .with_context(active_test=False)
            .search(
                [("name", "=", currency_code.upper())],
                limit=1,
            )
        )
        currency.action_unarchive()
        return currency

    @classmethod
    def _use_currency(cls, company, currency_code):
        currency = cls._enable_currency(currency_code)
        if company.currency_id != currency:
            cls.env.transaction.cache.set(
                cls.env.company,
                type(cls.env.company).currency_id,
                currency.id,
                dirty=True,
            )

    @classmethod
    def _create_partner(cls, **create_values):
        return cls.env["res.partner"].create(
            {
                "name": "Test Partner",
                "company_id": False,
                **create_values,
            }
        )

    @classmethod
    def _create_company(cls, **create_values):
        company = cls.env["res.company"].create(
            {
                "name": "Test Company",
                **create_values,
            }
        )
        cls.env.user.company_ids = [Command.link(company.id)]
        return company

    @classmethod
    def _create_new_internal_user(cls, **kwargs):
        return new_test_user(
            cls.env,
            **({"login": "internal_user"} | kwargs),
        )

    @classmethod
    def _create_new_portal_user(cls, **kwargs):
        return new_test_user(
            cls.env,
            groups="base.group_portal",
            **({"login": "portal_user"} | kwargs),
        )

    @classmethod
    def quick_ref(cls, xmlid):
        model, id = cls.env["ir.model.data"]._xmlid_to_res_model_res_id(xmlid)
        return cls.env[model].browse(id)


class TransactionCaseWithUserDemo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env.ref("base.partner_admin").write({"name": "Mitchell Admin"})
        cls.user_demo = cls.env["res.users"].search([("login", "=", "demo")])
        cls.partner_demo = cls.user_demo.partner_id

        if not cls.user_demo:
            cls.env["ir.config_parameter"].sudo().set_param(
                "auth_password_policy.minlength", 4
            )
            cls.partner_demo = cls.env["res.partner"].create(
                {
                    "name": "Marc Demo",
                    "email": "mark.brown23@example.com",
                }
            )
            cls.user_demo = cls.env["res.users"].create(
                {
                    "login": "demo",
                    "password": "demo",
                    "partner_id": cls.partner_demo.id,
                    "group_ids": [
                        Command.set(
                            [
                                cls.env.ref("base.group_user").id,
                                cls.env.ref("base.group_partner_manager").id,
                            ]
                        )
                    ],
                }
            )


class HttpCaseWithUserDemo(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_admin = cls.env.ref("base.user_admin")
        cls.user_admin.write({"name": "Mitchell Admin"})
        cls.partner_admin = cls.user_admin.partner_id
        cls.user_demo = cls.env["res.users"].search([("login", "=", "demo")])
        cls.partner_demo = cls.user_demo.partner_id

        if not cls.user_demo:
            cls.env["ir.config_parameter"].sudo().set_param(
                "auth_password_policy.minlength", 4
            )
            cls.partner_demo = cls.env["res.partner"].create(
                {
                    "name": "Marc Demo",
                    "email": "mark.brown23@example.com",
                    "tz": "UTC",
                }
            )
            cls.user_demo = cls.env["res.users"].create(
                {
                    "login": "demo",
                    "password": "demo",
                    "partner_id": cls.partner_demo.id,
                    "group_ids": [
                        Command.set(
                            [
                                cls.env.ref("base.group_user").id,
                                cls.env.ref("base.group_partner_manager").id,
                            ]
                        )
                    ],
                }
            )


class SavepointCaseWithUserDemo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user_demo = cls.env["res.users"].search([("login", "=", "demo")])
        cls.partner_demo = cls.user_demo.partner_id

        if not cls.user_demo:
            cls.env["ir.config_parameter"].sudo().set_param(
                "auth_password_policy.minlength", 4
            )
            cls.partner_demo = cls.env["res.partner"].create(
                {
                    "name": "Marc Demo",
                    "email": "mark.brown23@example.com",
                }
            )
            cls.user_demo = cls.env["res.users"].create(
                {
                    "login": "demo",
                    "password": "demo",
                    "partner_id": cls.partner_demo.id,
                    "group_ids": [
                        Command.set(
                            [
                                cls.env.ref("base.group_user").id,
                                cls.env.ref("base.group_partner_manager").id,
                            ]
                        )
                    ],
                }
            )

    @classmethod
    def _load_partners_set(cls):
        cls.partner_category = cls.env["res.partner.category"].create(
            {
                "name": "Sellers",
                "color": 2,
            }
        )
        cls.partner_category_child_1 = cls.env["res.partner.category"].create(
            {
                "name": "Office Supplies",
                "parent_id": cls.partner_category.id,
            }
        )
        cls.partner_category_child_2 = cls.env["res.partner.category"].create(
            {
                "name": "Desk Manufacturers",
                "parent_id": cls.partner_category.id,
            }
        )

        cls.partners = cls.env["res.partner"].create(
            [
                {
                    "name": "Inner Works",
                    "state_id": cls.env.ref("base.state_us_1").id,
                    "category_id": [
                        Command.set(
                            [
                                cls.partner_category_child_1.id,
                                cls.partner_category_child_2.id,
                            ]
                        )
                    ],
                    "child_ids": [
                        Command.create(
                            {
                                "name": "Sheila Ruiz",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Wyatt Howard",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Austin Kennedy",
                            }
                        ),
                    ],
                },
                {
                    "name": "Pepper Street",
                    "state_id": cls.env.ref("base.state_us_2").id,
                    "child_ids": [
                        Command.create(
                            {
                                "name": "Liam King",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Craig Richardson",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Adam Cox",
                            }
                        ),
                    ],
                },
                {
                    "name": "AnalytIQ",
                    "state_id": cls.env.ref("base.state_us_3").id,
                    "child_ids": [
                        Command.create(
                            {
                                "name": "Pedro Boyd",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Landon Roberts",
                                "company_id": cls.env.ref("base.main_company").id,
                            }
                        ),
                        Command.create(
                            {
                                "name": "Leona Shelton",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Scott Kim",
                            }
                        ),
                    ],
                },
                {
                    "name": "Urban Trends",
                    "state_id": cls.env.ref("base.state_us_4").id,
                    "category_id": [
                        Command.set(
                            [
                                cls.partner_category_child_1.id,
                                cls.partner_category_child_2.id,
                            ]
                        )
                    ],
                    "child_ids": [
                        Command.create(
                            {
                                "name": "Louella Jacobs",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Albert Alexander",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Brad Castillo",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Sophie Montgomery",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Chloe Bates",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Mason Crawford",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Elsie Kennedy",
                            }
                        ),
                    ],
                },
                {
                    "name": "Ctrl-Alt-Fix",
                    "state_id": cls.env.ref("base.state_us_5").id,
                    "child_ids": [
                        Command.create(
                            {
                                "name": "carole miller",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Cecil Holmes",
                            }
                        ),
                    ],
                },
                {
                    "name": "Ignitive Labs",
                    "state_id": cls.env.ref("base.state_us_6").id,
                    "child_ids": [
                        Command.create(
                            {
                                "name": "Jonathan Webb",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Clinton Clark",
                            }
                        ),
                        Command.create(
                            {
                                "name": "Howard Bryant",
                            }
                        ),
                    ],
                },
                {
                    "name": "Amber & Forge",
                    "state_id": cls.env.ref("base.state_us_7").id,
                    "child_ids": [
                        Command.create(
                            {
                                "name": "Mark Webb",
                            }
                        )
                    ],
                },
                {
                    "name": "Rebecca Day",
                    "parent_id": cls.env.ref("base.main_partner").id,
                },
                {
                    "name": "Gabriella Jennings",
                    "parent_id": cls.env.ref("base.main_partner").id,
                },
            ]
        )


class TransactionCaseWithUserPortal(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_portal = cls.env["res.users"].sudo().search([("login", "=", "portal")])
        cls.partner_portal = cls.user_portal.partner_id

        if not cls.user_portal:
            cls.env["ir.config_parameter"].sudo().set_param(
                "auth_password_policy.minlength", 4
            )
            cls.partner_portal = cls.env["res.partner"].create(
                {
                    "name": "Joel Willis",
                    "email": "joel.willis63@example.com",
                }
            )
            cls.user_portal = (
                cls.env["res.users"]
                .with_context(no_reset_password=True)
                .create(
                    {
                        "login": "portal",
                        "password": "portal",
                        "partner_id": cls.partner_portal.id,
                        "group_ids": [
                            Command.set([cls.env.ref("base.group_portal").id])
                        ],
                    }
                )
            )


class HttpCaseWithUserPortal(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_portal = cls.env["res.users"].sudo().search([("login", "=", "portal")])
        cls.partner_portal = cls.user_portal.partner_id

        if not cls.user_portal:
            cls.env["ir.config_parameter"].sudo().set_param(
                "auth_password_policy.minlength", 4
            )
            cls.partner_portal = cls.env["res.partner"].create(
                {
                    "name": "Joel Willis",
                    "email": "joel.willis63@example.com",
                }
            )
            cls.user_portal = (
                cls.env["res.users"]
                .with_context(no_reset_password=True)
                .create(
                    {
                        "login": "portal",
                        "password": "portal",
                        "partner_id": cls.partner_portal.id,
                        "group_ids": [
                            Command.set([cls.env.ref("base.group_portal").id])
                        ],
                    }
                )
            )


class MockSmtplibCase:
    @contextmanager
    def mock_smtplib_connection(self):
        self.emails = []

        origin = self

        class TestingSMTPSession:
            def quit(self):
                pass

            def send_message(self, message, smtp_from, smtp_to_list):
                origin.emails.append(
                    {
                        "message": message.as_string(),
                        "msg_cc": message["Cc"],
                        "msg_from": message["From"],
                        "msg_from_fmt": email_split_and_format(message["From"])[0],
                        "msg_to": message["To"],
                        "smtp_from": smtp_from,
                        "smtp_to_list": smtp_to_list,
                        "from_filter": self.from_filter,
                    }
                )

            def set_debuglevel(self, smtp_debug):
                pass

            def ehlo_or_helo_if_needed(self):
                pass

            def login(self, user, password):
                pass

            def starttls(self, keyfile=None, certfile=None, context=None):
                pass

        self.testing_smtp_session = TestingSMTPSession()

        IrMailServer = self.env["ir.mail_server"]
        connect_origin = type(IrMailServer)._connect__
        find_mail_server_origin = type(IrMailServer)._get_mail_server

        def mock_function(func):
            mock = Mock()

            def _call(*args, **kwargs):
                mock(*args[1:], **kwargs)
                return func(*args, **kwargs)

            _call.mock = mock
            return _call

        with (
            patch(
                "smtplib.SMTP_SSL",
                side_effect=lambda *args, **kwargs: self.testing_smtp_session,
            ),
            patch(
                "smtplib.SMTP",
                side_effect=lambda *args, **kwargs: self.testing_smtp_session,
            ),
            patch.object(type(IrMailServer), "_disable_send", lambda _: False),
            patch.object(
                type(IrMailServer), "_connect__", mock_function(connect_origin)
            ) as connect_mocked,
            patch.object(
                type(IrMailServer),
                "_get_mail_server",
                mock_function(find_mail_server_origin),
            ) as find_mail_server_mocked,
        ):
            self.connect_mocked = connect_mocked.mock
            self.find_mail_server_mocked = find_mail_server_mocked.mock
            yield

    def _build_email(self, mail_from, return_path=None, **kwargs):
        headers = {"Return-Path": return_path} if return_path else {}
        headers.update(**kwargs.pop("headers", {}))
        return self.env["ir.mail_server"]._prepare_email__(
            mail_from,
            kwargs.pop("email_to", "dest@example-é.com"),
            kwargs.pop("subject", "subject"),
            kwargs.pop("body", "body"),
            headers=headers,
            **kwargs,
        )

    def _send_email(self, msg, smtp_session):
        IrMailServer = self.env["ir.mail_server"]
        with patch.object(type(IrMailServer), "_disable_send", lambda _: False):
            IrMailServer.send_email(msg, smtp_session=smtp_session)
        return smtp_session.messages.pop()

    def assertSMTPEmailsSent(
        self,
        smtp_from=None,
        smtp_to_list=None,
        message_from=None,
        msg_from=None,
        mail_server=None,
        from_filter=None,
        emails_count=1,
        msg_cc_lst=None,
        msg_to_lst=None,
    ):
        if from_filter is not None and mail_server:
            msg = "Invalid usage: use either from_filter either mail_server"
            raise ValueError(msg)

        if from_filter is None and mail_server is not None:
            from_filter = mail_server.from_filter
        matching_emails = list(
            filter(
                lambda email: (
                    (smtp_from is None or smtp_from == email["smtp_from"])
                    and (smtp_to_list is None or smtp_to_list == email["smtp_to_list"])
                    and (
                        message_from is None
                        or "From: %s" % message_from in email["message"]
                    )
                    and (
                        msg_from is None
                        or (
                            msg_from == email["msg_from"]
                            or msg_from == email["msg_from_fmt"]
                        )
                    )
                    and (from_filter is None or from_filter == email["from_filter"])
                ),
                self.emails,
            )
        )

        debug_info = ""
        matching_emails_count = len(matching_emails)
        if matching_emails_count != emails_count:
            debug_info = "\n".join(
                f"SMTP-From: {email['smtp_from']}, SMTP-To: {email['smtp_to_list']}, "
                f"Msg-From: {email['msg_from']}, Msg-To: {email['msg_to']}, From_filter: {email['from_filter']})"
                for email in self.emails
            )
        self.assertEqual(
            matching_emails_count,
            emails_count,
            msg=f"Incorrect emails sent: {matching_emails_count} found, {emails_count} expected"
            f"\nConditions\nSMTP-From: {smtp_from}, SMTP-To: {smtp_to_list}, Msg-From: {message_from or msg_from}, From_filter: {from_filter}"
            f"\nNot found in\n{debug_info}",
        )
        if msg_to_lst is not None:
            for email in matching_emails:
                self.assertListEqual(
                    sorted(email_split_and_format(email["msg_to"])),
                    sorted(msg_to_lst),
                )
        if msg_cc_lst is not None:
            for email in matching_emails:
                self.assertListEqual(
                    sorted(email_split_and_format(email["msg_cc"])),
                    sorted(msg_cc_lst),
                )

    @classmethod
    def _init_mail_gateway(cls):
        cls.default_from_filter = False
        cls.env["ir.config_parameter"].sudo().set_param(
            "mail.default.from_filter", cls.default_from_filter
        )

    @classmethod
    def _init_mail_servers(cls):
        cls.env["ir.mail_server"].search([]).unlink()

        ir_mail_server_values = {
            "smtp_host": "smtp_host",
            "smtp_encryption": "none",
        }
        cls.mail_servers = cls.env["ir.mail_server"].create(
            [
                {
                    "name": "Domain based server",
                    "from_filter": "test.mycompany.com",
                    "sequence": 0,
                    **ir_mail_server_values,
                },
                {
                    "name": "User specific server",
                    "from_filter": "specific_user@test.mycompany.com",
                    "sequence": 1,
                    **ir_mail_server_values,
                },
                {
                    "name": "Server Notifications",
                    "from_filter": "notifications.test@test.mycompany.com",
                    "sequence": 2,
                    **ir_mail_server_values,
                },
                {
                    "name": "Server No From Filter",
                    "from_filter": False,
                    "sequence": 3,
                    **ir_mail_server_values,
                },
            ]
        )
        (
            cls.mail_server_domain,
            cls.mail_server_user,
            cls.mail_server_notification,
            cls.mail_server_default,
        ) = cls.mail_servers
