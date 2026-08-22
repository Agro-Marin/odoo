import contextlib
import json
from datetime import date
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged, users, warmup
from odoo.tools import formataddr, mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.mail.tests.common import MailCommon

_SEND_LOGGER = "odoo.addons.account.models.mixin_account_move_send"


@tagged("post_install_l10n", "post_install", "-at_install", "mail_flow")
class TestAccountComposerPerformance(AccountTestInvoicingCommon, MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.partner_a.email = "turlututu@tsointsoin"
        cls.user_accountman = (
            cls.env.user
        )
        cls.company_main = cls.company_data["company"]
        cls.move_template = cls.env["mail.template"].create(
            {
                "auto_delete": True,
                "body_html": '<p>TemplateBody for <t t-out="object.name"></t><t t-out="object.invoice_user_id.signature or \'\'"></t></p>',
                "description": "Sent to customers with their invoices in attachment",
                "email_from": "{{ (object.invoice_user_id.email_formatted or user.email_formatted) }}",
                "mail_server_id": cls.mail_server_default.id,
                "model_id": cls.env["ir.model"]._get_id("account.move"),
                "name": "Invoice: Test Sending",
                "partner_to": "{{ object.partner_id.id }}",
                "subject": "{{ object.company_id.name }} Invoice (Ref {{ object.name or 'n/a' }})",
                "report_template_ids": [
                    (4, cls.env.ref("account.account_invoices").id)
                ],
                "lang": "{{ object.partner_id.lang }}",
            }
        )
        cls.attachments = cls.env["ir.attachment"].create(
            cls._generate_attachments_data(
                2, cls.move_template._name, cls.move_template.id
            )
        )
        cls.move_template.write({"attachment_ids": [(6, 0, cls.attachments.ids)]})

        cls.user_account = (
            cls.env["res.users"]
            .with_context(cls._test_context)
            .create(
                {
                    "company_id": cls.company_main.id,
                    "company_ids": [Command.set(cls.company_data["company"].ids)],
                    "country_id": cls.env.ref("base.be").id,
                    "email": "e.e@example.com",
                    "group_ids": [
                        (
                            6,
                            0,
                            [
                                cls.env.ref("base.group_user").id,
                                cls.env.ref("account.group_account_invoice").id,
                                cls.env.ref("base.group_partner_manager").id,
                            ],
                        )
                    ],
                    "login": "user_account",
                    "name": "Ernest Employee Account",
                    "notification_type": "inbox",
                    "signature": "--\nErnest",
                }
            )
        )
        cls.user_account_other = (
            cls.env["res.users"]
            .with_context(cls._test_context)
            .create(
                {
                    "company_id": cls.company_admin.id,
                    "company_ids": [(4, cls.company_admin.id)],
                    "country_id": cls.env.ref("base.be").id,
                    "email": "e.e.other@example.com",
                    "group_ids": [
                        (
                            6,
                            0,
                            [
                                cls.env.ref("base.group_user").id,
                                cls.env.ref("account.group_account_invoice").id,
                                cls.env.ref("base.group_partner_manager").id,
                            ],
                        )
                    ],
                    "login": "user_account_other",
                    "name": "Eglantine Employee AccountOther",
                    "notification_type": "inbox",
                    "signature": "--\nEglantine",
                }
            )
        )

        country_id = cls.env.ref("base.be").id
        langs = ["en_US", "es_ES"]
        cls.env["res.lang"]._activate_lang("es_ES")
        cls.test_customers = cls.env["res.partner"].create(
            [
                {
                    "country_id": country_id,
                    "email": f"test_partner_{idx}@test.example.com",
                    "invoice_edi_format": False,
                    "phone": f"047500{idx:2d}{idx:2d}",
                    "lang": langs[idx % len(langs)],
                    "name": f"Partner_{idx}",
                }
                for idx in range(10)
            ]
        )
        cls.test_account_moves = cls.env["account.move"].create(
            [
                {
                    "invoice_date": date(2022, 3, 2),
                    "invoice_date_due": date(2022, 3, 10),
                    "invoice_line_ids": [
                        (0, 0, {"name": "Line1", "price_unit": 100.0}),
                        (0, 0, {"name": "Line2", "price_unit": 200.0}),
                    ],
                    "invoice_user_id": cls.user_account_other.id,
                    "move_type": "out_invoice",
                    "name": f"INVOICE_{idx:02d}",
                    "partner_id": cls.test_customers[idx].id,
                }
                for idx in range(10)
            ]
        )

        cls.test_account_moves.action_post()

        cls._activate_multi_lang(
            test_record=cls.test_account_moves,
            test_template=cls.move_template,
        )

    @classmethod
    def default_env_context(cls):
        return {}

    def setUp(self):
        super().setUp()

        self.patch(self.env.registry, "ready", True)
        self.flush_tracking()

    def test_assert_initial_values(self):
        for move in self.test_account_moves:
            with self.subTest(move=move):
                self.assertEqual(
                    move.invoice_user_id,
                    self.user_account_other,
                )
                self.assertEqual(
                    move.message_partner_ids,
                    self.user_accountman.partner_id,
                    "Customer should not be automatically added as follower",
                )

    @users("user_account")
    @warmup
    @mute_logger("odoo.addons.mail.models.mail_mail", "odoo.models.unlink")
    def test_move_composer_multi(self):
        test_moves = self.test_account_moves.with_env(self.env)
        test_customers = self.test_customers.with_env(self.env)
        move_template = self.move_template.with_env(self.env)

        for test_move in test_moves:
            self.assertFalse(test_move.is_move_sent)

        with self.mock_mail_gateway(mail_unlink_sent=False):
            self.env["mixin.account.move.send"]._generate_and_send_invoices(
                test_moves,
                sending_methods=["email"],
                mail_template=move_template,
            )

        self.assertEqual(
            len(self._mails),
            20,
            "Should send an email to each invoice followers (accountman + partner)",
        )
        for move, customer in zip(test_moves, test_customers, strict=False):
            with self.subTest(move=move, customer=customer):
                _exp_move_name = move.name
                _exp_report_name = f"{move.name}.pdf"
                if move.partner_id.lang == "es_ES":
                    _exp_body_tip = f"SpanishBody for {move.name}"
                    _exp_subject = f"SpanishSubject for {move.name}"
                else:
                    _exp_body_tip = f"TemplateBody for {move.name}"
                    _exp_subject = (
                        f"{self.env.user.company_id.name} Invoice (Ref {move.name})"
                    )

                self.assertEqual(move.partner_id, customer)
                self.assertMailMail(
                    customer,
                    "sent",
                    author=self.user_account_other.partner_id,
                    content=_exp_body_tip,
                    email_values={
                        "attachments_info": [
                            {
                                "name": "AttFileName_00.txt",
                                "raw": b"AttContent_00",
                                "type": "text/plain",
                            },
                            {
                                "name": "AttFileName_01.txt",
                                "raw": b"AttContent_01",
                                "type": "text/plain",
                            },
                            {"name": _exp_report_name, "type": "application/pdf"},
                        ],
                        "body_content": _exp_body_tip,
                        "email_from": self.user_account_other.email_formatted,
                        "subject": _exp_subject,
                        "reply_to": formataddr(
                            (
                                self.user_account_other.name,
                                f"{self.alias_catchall}@{self.alias_domain}",
                            )
                        ),
                    },
                    fields_values={
                        "auto_delete": True,
                        "email_from": self.user_account_other.email_formatted,
                        "is_notification": True,
                        "mail_server_id": self.mail_server_default,
                        "subject": _exp_subject,
                        "reply_to": formataddr(
                            (
                                self.user_account_other.name,
                                f"{self.alias_catchall}@{self.alias_domain}",
                            )
                        ),
                    },
                )

        for test_move in test_moves:
            self.assertTrue(test_move.is_move_sent)

    @users("user_account")
    @warmup
    @mute_logger("odoo.addons.mail.models.mail_mail", "odoo.models.unlink")
    def test_move_composer_single(self):
        test_move = self.test_account_moves[0].with_env(self.env)
        test_customer = self.test_customers[0].with_env(self.env)
        move_template = self.move_template.with_env(self.env)

        composer = (
            self.env["account.move.send.wizard"]
            .with_context(active_model="account.move", active_ids=test_move.ids)
            .create(
                {
                    "sending_methods": ["email"],
                    "template_id": move_template.id,
                }
            )
        )

        with self.mock_mail_gateway(mail_unlink_sent=False), self.mock_mail_app():
            composer.action_send_and_print(allow_fallback_pdf=True)
            self.env.cr.flush()

        new_account_msgs = self._new_msgs.filtered(
            lambda msg: (msg.model or "").startswith("account")
        )
        self.assertEqual(
            len(new_account_msgs), 1, "Should produce 1 message (for posting template)"
        )
        print_msg = new_account_msgs[0]
        self.assertNotified(
            print_msg,
            [
                {
                    "is_read": True,
                    "partner": test_customer,
                    "type": "email",
                }
            ],
        )

        self.assertEqual(len(print_msg.attachment_ids), 3)
        self.assertNotIn(
            self.attachments,
            print_msg.attachment_ids,
            "Attachments should be duplicated, not just linked",
        )
        self.assertEqual(
            print_msg.author_id,
            self.user_account_other.partner_id,
            "Should take invoice_user_id partner",
        )
        self.assertEqual(
            print_msg.email_from,
            self.user_account_other.email_formatted,
            "Should take invoice_user_id email",
        )
        self.assertEqual(
            print_msg.notified_partner_ids,
            test_customer + self.user_accountman.partner_id,
        )
        self.assertEqual(
            print_msg.subject,
            f"{self.env.user.company_id.name} Invoice (Ref {test_move.name})",
        )
        self.assertMailMail(
            test_customer,
            "sent",
            author=self.user_account_other.partner_id,
            content=f"TemplateBody for {test_move.name}",
            email_values={
                "attachments_info": [
                    {
                        "name": "AttFileName_00.txt",
                        "raw": b"AttContent_00",
                        "type": "text/plain",
                    },
                    {
                        "name": "AttFileName_01.txt",
                        "raw": b"AttContent_01",
                        "type": "text/plain",
                    },
                    {"name": f"{test_move.name}.pdf", "type": "application/pdf"},
                ],
                "body_content": f"TemplateBody for {test_move.name}",
                "email_from": self.user_account_other.email_formatted,
                "subject": f"{self.env.user.company_id.name} Invoice (Ref {test_move.name})",
                "reply_to": formataddr(
                    (
                        self.user_account_other.name,
                        f"{self.alias_catchall}@{self.alias_domain}",
                    )
                ),
            },
            fields_values={
                "auto_delete": True,
                "email_from": self.user_account_other.email_formatted,
                "is_notification": True,
                "mail_server_id": self.mail_server_default,
                "subject": f"{self.env.user.company_id.name} Invoice (Ref {test_move.name})",
                "reply_to": formataddr(
                    (
                        self.user_account_other.name,
                        f"{self.alias_catchall}@{self.alias_domain}",
                    )
                ),
            },
        )

        self.assertIn(f"TemplateBody for {test_move.name}", composer.body)
        self.assertEqual(composer.move_id, test_move)
        self.assertTrue("email" in composer.sending_methods)
        self.assertEqual(
            composer.subject,
            f"{self.env.user.company_id.name} Invoice (Ref {test_move.name})",
        )
        self.assertEqual(composer.template_id, move_template)

        self.assertTrue(test_move.is_move_sent)

    @users("user_account")
    @warmup
    @mute_logger("odoo.addons.mail.models.mail_mail", "odoo.models.unlink")
    def test_move_composer_single_lang(self):
        test_move = self.test_account_moves[1].with_env(self.env)
        test_customer = self.test_customers[1].with_env(self.env)
        move_template = self.move_template.with_env(self.env)

        composer = (
            self.env["account.move.send.wizard"]
            .with_context(active_model="account.move", active_ids=test_move.ids)
            .create(
                {
                    "sending_methods": ["email"],
                    "template_id": move_template.id,
                }
            )
        )

        with self.mock_mail_gateway(mail_unlink_sent=False), self.mock_mail_app():
            composer.action_send_and_print()
            self.env.cr.flush()

        new_account_msgs = self._new_msgs.filtered(
            lambda msg: (msg.model or "").startswith("account")
        )
        self.assertEqual(
            len(new_account_msgs), 1, "Should produce 1 message (for posting template)"
        )
        print_msg = new_account_msgs[0]
        self.assertNotified(
            print_msg,
            [
                {
                    "is_read": True,
                    "partner": test_customer,
                    "type": "email",
                }
            ],
        )

        self.assertEqual(len(print_msg.attachment_ids), 3)
        self.assertNotIn(
            self.attachments,
            print_msg.attachment_ids,
            "Attachments should be duplicated, not just linked",
        )
        self.assertEqual(
            print_msg.author_id,
            self.user_account_other.partner_id,
            "Should take invoice_user_id partner",
        )
        self.assertEqual(
            print_msg.email_from,
            self.user_account_other.email_formatted,
            "Should take invoice_user_id email",
        )
        self.assertEqual(
            print_msg.notified_partner_ids,
            test_customer + self.user_accountman.partner_id,
        )
        self.assertEqual(print_msg.subject, f"SpanishSubject for {test_move.name}")
        self.assertMailMail(
            test_customer,
            "sent",
            author=self.user_account_other.partner_id,
            content=f"SpanishBody for {test_move.name}",
            email_values={
                "attachments_info": [
                    {
                        "name": "AttFileName_00.txt",
                        "raw": b"AttContent_00",
                        "type": "text/plain",
                    },
                    {
                        "name": "AttFileName_01.txt",
                        "raw": b"AttContent_01",
                        "type": "text/plain",
                    },
                    {"name": f"{test_move.name}.pdf", "type": "application/pdf"},
                ],
                "body_content": f"SpanishBody for {test_move.name}",
                "email_from": self.user_account_other.email_formatted,
                "subject": f"SpanishSubject for {test_move.name}",
                "reply_to": formataddr(
                    (
                        self.user_account_other.name,
                        f"{self.alias_catchall}@{self.alias_domain}",
                    )
                ),
            },
            fields_values={
                "auto_delete": True,
                "email_from": self.user_account_other.email_formatted,
                "is_notification": True,
                "mail_server_id": self.mail_server_default,
                "subject": f"SpanishSubject for {test_move.name}",
                "reply_to": formataddr(
                    (
                        self.user_account_other.name,
                        f"{self.alias_catchall}@{self.alias_domain}",
                    )
                ),
            },
        )

        self.assertIn(
            f"SpanishBody for {test_move.name}",
            composer.body,
            "Should be translated, based on template",
        )
        self.assertEqual(composer.move_id, test_move)
        self.assertTrue("email" in composer.sending_methods)
        self.assertEqual(
            composer.subject,
            f"SpanishSubject for {test_move.name}",
            "Should be translated, based on template",
        )
        self.assertEqual(composer.template_id, move_template)

        self.assertTrue(test_move.is_move_sent)

    @users("user_account")
    @warmup
    @mute_logger("odoo.addons.mail.models.mail_mail", "odoo.models.unlink")
    def test_move_composer_with_dynamic_reports(self):
        test_move = self.test_account_moves[0].with_env(self.env)
        test_customer = self.test_customers[0].with_env(self.env)
        move_template = self.move_template.with_env(self.env)

        extra_dynamic_report = self.env.ref(
            "account.action_account_original_vendor_bill"
        )
        move_template.report_template_ids += extra_dynamic_report

        composer = (
            self.env["account.move.send.wizard"]
            .with_context(active_model="account.move", active_ids=test_move.ids)
            .create(
                {
                    "sending_methods": ["email"],
                    "template_id": move_template.id,
                }
            )
        )

        with self.mock_mail_gateway(mail_unlink_sent=False), self.mock_mail_app():
            composer.action_send_and_print()
            self.env.cr.flush()

        self.assertMailMail(
            test_customer,
            "sent",
            author=self.user_account_other.partner_id,
            content=f"TemplateBody for {test_move.name}",
            email_values={
                "attachments_info": [
                    {
                        "name": "AttFileName_00.txt",
                        "raw": b"AttContent_00",
                        "type": "text/plain",
                    },
                    {
                        "name": "AttFileName_01.txt",
                        "raw": b"AttContent_01",
                        "type": "text/plain",
                    },
                    {"name": f"{test_move.name}.pdf", "type": "application/pdf"},
                    {
                        "name": f"{extra_dynamic_report.name.lower()}_{test_move.name}.pdf",
                        "type": "application/pdf",
                    },
                ],
                "body_content": f"TemplateBody for {test_move.name}",
                "email_from": self.user_account_other.email_formatted,
                "subject": f"{self.env.user.company_id.name} Invoice (Ref {test_move.name})",
                "reply_to": formataddr(
                    (
                        self.user_account_other.name,
                        f"{self.alias_catchall}@{self.alias_domain}",
                    )
                ),
            },
            fields_values={
                "auto_delete": True,
                "email_from": self.user_account_other.email_formatted,
                "is_notification": True,
                "mail_server_id": self.mail_server_default,
                "subject": f"{self.env.user.company_id.name} Invoice (Ref {test_move.name})",
                "reply_to": formataddr(
                    (
                        self.user_account_other.name,
                        f"{self.alias_catchall}@{self.alias_domain}",
                    )
                ),
            },
        )

    def test_invoice_sent_to_additional_partner(self):
        test_move = self.test_account_moves[1].with_env(self.env)
        move_template = self.move_template.with_env(self.env)

        additional_partner = self.env["res.partner"].create(
            {
                "name": "Additional Partner",
                "email": "additional@example.com",
            }
        )

        composer = (
            self.env["account.move.send.wizard"]
            .with_context(active_model="account.move", active_ids=test_move.ids)
            .create(
                {
                    "sending_methods": ["email"],
                    "template_id": move_template.id,
                    "mail_partner_ids": additional_partner.ids,
                }
            )
        )

        with self.mock_mail_gateway(mail_unlink_sent=False):
            composer.action_send_and_print()

        self.assertMailMail(
            additional_partner,
            "sent",
            author=self.user_account_other.partner_id,
            content="access_token=",
        )


class TestAccountMoveSendCommon(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.partner_a.email = "partner_a@tsointsoin"
        cls.partner_b.email = "partner_b@tsointsoin"

    def _assert_mail_attachments_widget(self, wizard, expected_values_list):
        self.assertEqual(len(wizard.mail_attachments_widget), len(expected_values_list))
        for values, expected_values in zip(
            wizard.mail_attachments_widget, expected_values_list, strict=False
        ):
            try:
                int(values["id"])
                check_id_needed = True
            except ValueError:
                check_id_needed = False
            self.assertDictEqual(
                {k: v for k, v in values.items() if not check_id_needed and k != "id"},
                {
                    k: v
                    for k, v in expected_values.items()
                    if not check_id_needed and k != "id"
                },
            )

    def create_send_and_print(self, invoices, default=False, **kwargs):
        invoices.action_send_and_print()
        if len(invoices) == 1:
            if not default and not kwargs.get("sending_methods"):
                kwargs["sending_methods"] = []
            return self._create_account_move_send_wizard_single(invoices, **kwargs)
        else:
            return self._create_account_move_send_wizard_multi(invoices, **kwargs)

    def _get_mail_message(self, move, limit=1):
        return self.env["mail.message"].search(
            [("model", "=", move._name), ("res_id", "=", move.id)], limit=limit
        )


@tagged("post_install_l10n", "post_install", "-at_install", "mail_template")
class TestAccountMoveSend(TestAccountMoveSendCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_data_2 = cls.setup_other_company()
        (
            cls.partner_a.with_company(cls.company_data["company"].id)
            + cls.partner_b.with_company(cls.company_data["company"].id)
        ).write(
            {
                "invoice_sending_method": "email",
                "email": "turlututu@tsointsoin",
            }
        )
        (
            cls.partner_a.with_company(cls.company_data_2["company"].id)
            + cls.partner_b.with_company(cls.company_data_2["company"].id)
        ).write(
            {
                "invoice_sending_method": "email",
                "email": "turlututu@tsointsoin",
            }
        )

    def test_invoice_single(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        wizard = self.create_send_and_print(
            invoice, sending_methods=["email", "manual"]
        )
        self.assertRecordValues(
            wizard,
            [
                {
                    "move_id": invoice.id,
                    "sending_methods": ["email", "manual"],
                    "extra_edis": False,
                    "extra_edi_checkboxes": False,
                    "pdf_report_id": wizard._get_default_pdf_report_id(invoice).id,
                    "display_pdf_report_id": False,
                    "template_id": wizard._get_default_mail_template_id(invoice).id,
                    "lang": "en_US",
                    "mail_partner_ids": wizard.move_id.partner_id.ids,
                }
            ],
        )
        self.assertFalse(wizard.alerts)
        self.assertTrue(wizard.subject)
        self.assertTrue(wizard.body)
        self._assert_mail_attachments_widget(
            wizard,
            [
                {
                    "mimetype": "application/pdf",
                    "name": invoice._get_invoice_report_filename(),
                    "placeholder": True,
                }
            ],
        )

        results = wizard.action_send_and_print()
        self.assertEqual(results["type"], "ir.actions.act_url")
        self.assertFalse(invoice.sending_data)

        pdf_report = invoice.invoice_pdf_report_id
        self.assertTrue(pdf_report)
        invoice_attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", invoice._name),
                ("res_id", "=", invoice.id),
                ("res_field", "=", "invoice_pdf_report_file"),
            ]
        )
        self.assertEqual(len(invoice_attachments), 1)
        self.assertTrue(self._get_mail_message(invoice))

        wizard = self.create_send_and_print(
            invoice, sending_methods=["email", "manual"]
        )
        with patch(
            "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._hook_invoice_document_after_pdf_report_render"
        ) as mocked_method:
            results = wizard.action_send_and_print()
            mocked_method.assert_not_called()
        self.assertEqual(results["type"], "ir.actions.act_url")
        self.assertFalse(invoice.sending_data)
        self.assertRecordValues(invoice, [{"invoice_pdf_report_id": pdf_report.id}])
        invoice_attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", invoice._name),
                ("res_id", "=", invoice.id),
                ("res_field", "=", "invoice_pdf_report_file"),
            ]
        )
        self.assertEqual(len(invoice_attachments), 1)
        self.assertTrue(self._get_mail_message(invoice))

        invoice_attachments = self.env["ir.attachment"].search(
            [
                ("name", "=", pdf_report.name),
                ("res_model", "=", invoice._name),
                ("res_id", "=", invoice.id),
                ("res_field", "=", False),
            ]
        )
        self.assertFalse(invoice_attachments)

    def test_invoice_multi(self):
        invoice1 = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[1000], post=True
        )
        invoice2 = self.init_invoice(
            "out_invoice", partner=self.partner_b, amounts=[1000], post=True
        )

        self.partner_a.invoice_sending_method = "email"
        self.partner_b.invoice_sending_method = "manual"

        wizard = self.create_send_and_print(invoice1 + invoice2)
        self.assertEqual(wizard.move_ids, invoice1 + invoice2)
        self.assertFalse(wizard.alerts)
        self.assertEqual(
            wizard.summary_data,
            {
                "manual": {"count": 1, "label": "Manually"},
                "email": {"count": 1, "label": "by Email"},
            },
        )

        results = wizard.action_send_and_print()
        self.assertEqual(results["type"], "ir.actions.client")
        self.assertEqual(
            results["params"]["next"]["type"], "ir.actions.act_window_close"
        )

        self.assertFalse(invoice1.invoice_pdf_report_id)
        self.assertFalse(invoice2.invoice_pdf_report_id)
        self.assertTrue(invoice1.is_being_sent)
        self.assertTrue(invoice2.is_being_sent)

        with self.enter_registry_test_mode():
            self.env.ref("account.ir_cron_account_move_send").method_direct_trigger()
        self.assertTrue(invoice1.invoice_pdf_report_id)
        invoice_attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", invoice1._name),
                ("res_id", "=", invoice1.id),
                ("res_field", "=", "invoice_pdf_report_file"),
            ]
        )
        self.assertTrue(self._get_mail_message(invoice1))
        self.assertEqual(len(invoice_attachments), 1)
        self.assertTrue(invoice2.invoice_pdf_report_id)
        invoice_attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", invoice2._name),
                ("res_id", "=", invoice2.id),
                ("res_field", "=", "invoice_pdf_report_file"),
            ]
        )
        self.assertEqual(len(invoice_attachments), 1)
        self.assertFalse(invoice1.is_being_sent)
        self.assertFalse(invoice2.is_being_sent)

        invoice3 = self.init_invoice(
            "out_invoice", partner=self.partner_b, amounts=[1000], post=True
        )
        wizard = self.create_send_and_print(invoice1 + invoice2 + invoice3)
        self.assertEqual(wizard.move_ids, invoice1 + invoice2 + invoice3)
        self.assertEqual(
            wizard.summary_data,
            {
                "manual": {"count": 2, "label": "Manually"},
                "email": {"count": 1, "label": "by Email"},
            },
        )
        wizard.action_send_and_print()
        with self.enter_registry_test_mode():
            self.env.ref("account.ir_cron_account_move_send").method_direct_trigger()
        invoice_attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", invoice1._name),
                ("res_id", "=", invoice1.id),
                ("res_field", "=", "invoice_pdf_report_file"),
            ]
        )
        self.assertEqual(len(invoice_attachments), 1)
        invoice_attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", invoice2._name),
                ("res_id", "=", invoice2.id),
                ("res_field", "=", "invoice_pdf_report_file"),
            ]
        )
        self.assertEqual(len(invoice_attachments), 1)
        self.assertTrue(invoice1.invoice_pdf_report_id)
        invoice_attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", invoice3._name),
                ("res_id", "=", invoice3.id),
                ("res_field", "=", "invoice_pdf_report_file"),
            ]
        )
        self.assertEqual(len(invoice_attachments), 1)

    def test_compute_value_of_send_invoice_batch_wizard(self):
        invoices = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[1000], post=True
        ) + self.init_invoice(
            "out_invoice", partner=self.partner_b, amounts=[1000], post=True
        )
        template = self.env.ref("account.email_template_edi_invoice")
        template.write(
            {
                "use_default_to": False,
                "email_cc": "demo@gmail.com",
            }
        )

        move_send_batch_wizard = Form(
            self.env["account.move.send.batch.wizard"].with_context(
                active_model="account.move", active_ids=invoices.ids
            )
        )

        self.assertEqual(move_send_batch_wizard.move_ids.ids, invoices.ids)
        self.assertEqual(
            move_send_batch_wizard.summary_data,
            {"email": {"count": len(invoices), "label": "by Email"}},
        )
        self.assertFalse(move_send_batch_wizard.alerts)

    def test_invoice_multi_email_missing(self):
        invoice1 = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[1000], post=True
        )
        invoice2 = self.init_invoice(
            "out_invoice", partner=self.partner_b, amounts=[1000], post=True
        )

        self.partner_a.email = None
        self.assertTrue(bool(self.partner_b.email))
        wizard = self.create_send_and_print(invoice1 + invoice2)
        self.assertEqual(
            wizard.summary_data,
            {
                "email": {
                    "count": 1,
                    "label": "by Email",
                },
            },
        )
        self.assertTrue("account_missing_email" in wizard.alerts)
        self.assertEqual(wizard.alerts["account_missing_email"]["level"], "warning")
        wizard.action_send_and_print()
        with self.enter_registry_test_mode():
            self.env.ref("account.ir_cron_account_move_send").method_direct_trigger()
        self.assertTrue(invoice1.invoice_pdf_report_id)
        self.assertFalse(self._get_mail_message(invoice1, limit=None).partner_ids)
        self.assertTrue(invoice2.invoice_pdf_report_id)
        self.assertTrue(self._get_mail_message(invoice2, limit=None).partner_ids)

    def test_invoice_multi_with_edi(self):
        invoice1 = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[1000], post=True
        )
        invoice2 = self.init_invoice(
            "out_invoice", partner=self.partner_b, amounts=[1000], post=True
        )

        self.partner_a.invoice_sending_method = "email"
        self.partner_b.invoice_sending_method = "manual"

        def get_default_extra_edis(self, move):
            if move == invoice1:
                return {"edi1"}
            return {"edi1", "edi2"}

        def get_all_extra_edis(self):
            return {
                "edi1": {"label": "EDI 1"},
                "edi2": {"label": "EDI 2"},
            }

        with (
            patch(
                "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._get_default_extra_edis",
                get_default_extra_edis,
            ),
            patch(
                "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._get_all_extra_edis",
                get_all_extra_edis,
            ),
        ):
            wizard = self.create_send_and_print(invoice1 + invoice2)
            self.assertEqual(
                wizard.summary_data,
                {
                    "edi1": {"count": 2, "label": "by EDI 1"},
                    "edi2": {"count": 1, "label": "by EDI 2"},
                    "manual": {"count": 1, "label": "Manually"},
                    "email": {"count": 1, "label": "by Email"},
                },
            )

    def test_invoice_multi_child_contact(self):
        self.partner_a.write({"invoice_sending_method": "manual"})
        partner = self.env["res.partner"].create(
            {
                "type": "invoice",
                "email": "child@example.com",
                "parent_id": self.partner_a.id,
            }
        )
        invoice1 = self.init_invoice(
            "out_invoice", amounts=[1000], partner=partner, post=True
        )
        invoice2 = self.init_invoice(
            "out_invoice", amounts=[1000], partner=partner, post=True
        )
        wizard = self.create_send_and_print(invoice1 + invoice2)
        self.assertEqual(
            wizard.summary_data, {"manual": {"count": 2, "label": "Manually"}}
        )

    def test_invoice_mail_attachments_widget(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)

        template = invoice._get_mail_template()
        extra_attachment = self.env["ir.attachment"].create(
            {"name": "extra_attachment", "raw": b"bar"}
        )
        template.attachment_ids = [Command.link(extra_attachment.id)]

        wizard = self.create_send_and_print(
            invoice, sending_methods=["email"], template_id=template.id
        )
        pdf_report_values = {
            "mimetype": "application/pdf",
            "name": "INV_2019_00001.pdf",
            "placeholder": True,
        }
        extra_attachment_values = {
            "mimetype": "application/octet-stream",
            "name": extra_attachment.name,
            "placeholder": False,
            "template_id": template.id,
        }
        self._assert_mail_attachments_widget(
            wizard, [pdf_report_values, extra_attachment_values]
        )

        manual_attachment = self.env["ir.attachment"].create(
            {"name": "manual_attachment", "raw": b"foo"}
        )
        manual_attachment_values = {
            "id": manual_attachment.id,
            "name": manual_attachment.name,
            "mimetype": manual_attachment.mimetype,
            "placeholder": False,
            "manual": True,
        }
        wizard.mail_attachments_widget += [manual_attachment_values]

        new_mail_template = wizard.template_id.copy()
        extra_attachment2 = self.env["ir.attachment"].create(
            {"name": "extra_attachment2", "raw": b"bar"}
        )
        new_mail_template.attachment_ids = [Command.set(extra_attachment2.ids)]
        extra_attachment2_values = {
            "mimetype": "application/octet-stream",
            "name": extra_attachment2.name,
            "placeholder": False,
            "template_id": new_mail_template.id,
        }

        wizard.template_id = new_mail_template
        self._assert_mail_attachments_widget(
            wizard,
            [
                pdf_report_values,
                extra_attachment2_values,
                manual_attachment_values,
            ],
        )

        wizard.action_send_and_print()
        message = self._get_mail_message(invoice)
        self.assertRecordValues(
            message.attachment_ids.sorted("name"),
            [
                {
                    "name": invoice.invoice_pdf_report_id.name,
                    "datas": invoice.invoice_pdf_report_id.datas,
                },
                {
                    "name": extra_attachment2.name,
                    "datas": extra_attachment2.datas,
                },
                {
                    "name": manual_attachment.name,
                    "datas": manual_attachment.datas,
                },
            ],
        )

        wizard = self.create_send_and_print(invoice, sending_methods=["email"])
        pdf_report_values["id"] = invoice.invoice_pdf_report_id.id
        self._assert_mail_attachments_widget(
            wizard,
            [
                pdf_report_values,
                extra_attachment_values,
            ],
        )

        wizard.template_id = new_mail_template
        self._assert_mail_attachments_widget(
            wizard,
            [
                pdf_report_values,
                extra_attachment2_values,
            ],
        )

        wizard.action_send_and_print()
        message = self._get_mail_message(invoice)
        self.assertRecordValues(
            message.attachment_ids.sorted("name"),
            [
                {
                    "name": invoice.invoice_pdf_report_id.name,
                    "datas": invoice.invoice_pdf_report_id.datas,
                },
                {
                    "name": extra_attachment2.name,
                    "datas": extra_attachment2.datas,
                },
            ],
        )

        invoice_pdf_report_name = invoice.invoice_pdf_report_id.name
        invoice_pdf_report_datas = invoice.invoice_pdf_report_id.datas
        invoice.invoice_pdf_report_id.unlink()
        self.assertRecordValues(
            message.attachment_ids.sorted("name"),
            [
                {
                    "name": invoice_pdf_report_name,
                    "datas": invoice_pdf_report_datas,
                },
                {
                    "name": extra_attachment2.name,
                    "datas": extra_attachment2.datas,
                },
            ],
        )

    def test_invoice_web_service_after_pdf_rendering(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        wizard = self.create_send_and_print(invoice)

        def call_web_service_after_invoice_pdf_render(record, invoices_data):
            for invoice_data in invoices_data.values():
                invoice_data["error"] = {"error_title": "turlututu"}

        with patch(
            "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._call_web_service_after_invoice_pdf_render",
            call_web_service_after_invoice_pdf_render,
        ):
            with contextlib.suppress(UserError):
                wizard.action_send_and_print(allow_fallback_pdf=False)

        self.assertFalse(invoice.invoice_pdf_report_id)

    def test_proforma_pdf(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        wizard = self.create_send_and_print(invoice, sending_methods=["email"])

        def _hook_invoice_document_before_pdf_report_render(
            self, invoice, invoice_data
        ):
            invoice_data["error"] = {"error_title": "test_proforma_pdf"}

        with patch(
            "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._hook_invoice_document_before_pdf_report_render",
            _hook_invoice_document_before_pdf_report_render,
        ):
            results = wizard.action_send_and_print(allow_fallback_pdf=True)

        self.assertEqual(results["type"], "ir.actions.act_window_close")
        self.assertFalse(invoice.sending_data)

        self.assertFalse(invoice.invoice_pdf_report_id)
        self.assertEqual(
            invoice.message_main_attachment_id.name, "INV_2019_00001_proforma.pdf"
        )

    def test_error_but_continue(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        wizard = self.create_send_and_print(invoice, sending_methods=["email"])

        def _hook_invoice_document_before_pdf_report_render(
            self, invoice, invoice_data
        ):
            invoice_data["error"] = {"error_title": "prout"}
            invoice_data["error_but_continue"] = True

        with patch(
            "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._hook_invoice_document_before_pdf_report_render",
            _hook_invoice_document_before_pdf_report_render,
        ):
            results = wizard.action_send_and_print(allow_fallback_pdf=True)

        self.assertEqual(results["type"], "ir.actions.act_window_close")
        self.assertFalse(invoice.sending_data)

        self.assertFalse(invoice.invoice_pdf_report_id)
        self.assertEqual(
            invoice.message_main_attachment_id.name, "INV_2019_00001_proforma.pdf"
        )

    def test_with_empty_mail_template_single(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)

        custom_subject = "turlututu"
        wizard = self.create_send_and_print(invoice, sending_methods=["email"])
        wizard.template_id = None
        wizard.subject = custom_subject

        wizard.action_send_and_print(allow_fallback_pdf=True)
        message = self._get_mail_message(invoice)
        self.assertRecordValues(message, [{"subject": custom_subject}])

    def test_with_empty_mail_template_multi(self):
        invoice_1 = self.init_invoice(
            "out_invoice", amounts=[1000], partner=self.partner_a, post=True
        )
        invoice_2 = self.init_invoice(
            "out_invoice", amounts=[1000], partner=self.partner_a, post=True
        )
        self.assertRecordValues(
            self.partner_a,
            [
                {
                    "email": "turlututu@tsointsoin",
                    "invoice_sending_method": "email",
                }
            ],
        )
        wizard = self.create_send_and_print(invoice_1 + invoice_2)

        wizard.action_send_and_print()
        with self.enter_registry_test_mode():
            self.env.ref("account.ir_cron_account_move_send").method_direct_trigger()
        self.assertTrue(invoice_1.invoice_pdf_report_id)
        self.assertTrue(invoice_2.invoice_pdf_report_id)

    def test_with_draft_invoices(self):
        invoice_posted = self.init_invoice("out_invoice", amounts=[1000], post=True)
        invoice_draft = self.init_invoice("out_invoice", amounts=[1000], post=False)

        with self.assertRaises(UserError):
            self.create_send_and_print(invoice_draft)
        with self.assertRaises(UserError):
            self.create_send_and_print(invoice_posted + invoice_draft)

    def test_link_pdf_webservice_fails_after(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        wizard = self.create_send_and_print(invoice)

        def _call_web_service_after_invoice_pdf_render(self, invoices_data):
            for move_data in invoices_data.values():
                move_data["error"] = {"error_title": "service_failed_after"}

        with patch(
            "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._call_web_service_after_invoice_pdf_render",
            _call_web_service_after_invoice_pdf_render,
        ):
            wizard.action_send_and_print(allow_fallback_pdf=True)

        self.assertTrue(invoice.invoice_pdf_report_id)
        self.assertFalse(
            self.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("name", "=", invoice._get_invoice_proforma_pdf_report_filename()),
                ]
            )
        )

    def test_link_pdf_webservice_fails_before(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        wizard = self.create_send_and_print(invoice)

        def _call_web_service_before_invoice_pdf_render(self, invoices_data):
            for move_data in invoices_data.values():
                move_data["error"] = {"error_title": "service_failed_before"}

        with patch(
            "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._call_web_service_before_invoice_pdf_render",
            _call_web_service_before_invoice_pdf_render,
        ):
            wizard.action_send_and_print(allow_fallback_pdf=True)

        self.assertFalse(invoice.invoice_pdf_report_id)
        self.assertTrue(
            self.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("name", "=", invoice._get_invoice_proforma_pdf_report_filename()),
                ]
            )
        )

    def test_send_and_print_cron(self):
        invoice_1_1 = self.init_invoice(
            "out_invoice",
            amounts=[1000],
            post=True,
            company=self.company_data["company"],
        )
        invoice_1_2 = self.init_invoice(
            "out_invoice",
            amounts=[1000],
            post=True,
            company=self.company_data["company"],
        )
        wizard = self.create_send_and_print(invoice_1_1 + invoice_1_2)
        wizard.action_send_and_print()

        invoice_2_1 = self.init_invoice(
            "out_invoice",
            amounts=[1000],
            post=True,
            company=self.company_data_2["company"],
        )
        invoice_2_2 = self.init_invoice(
            "out_invoice",
            amounts=[1000],
            post=True,
            company=self.company_data_2["company"],
        )
        wizard_2 = self.create_send_and_print(invoice_2_1 + invoice_2_2)
        wizard_2.action_send_and_print()

        invoices = invoice_1_1 + invoice_1_2 + invoice_2_1 + invoice_2_2
        invoices = invoices.sudo()
        self.assertFalse(invoices.invoice_pdf_report_id)
        self.assertTrue(all(invoice.sending_data for invoice in invoices))
        with self.enter_registry_test_mode():
            self.env.ref("account.ir_cron_account_move_send").method_direct_trigger()
        self.assertTrue(all(invoice.invoice_pdf_report_id for invoice in invoices))
        self.assertTrue(all(not invoice.sending_data for invoice in invoices))

    def test_cron_send_isolates_failing_move(self):
        invoice_ok = self.init_invoice(
            "out_invoice",
            amounts=[1000],
            post=True,
            company=self.company_data["company"],
        )
        invoice_ko = self.init_invoice(
            "out_invoice",
            amounts=[1000],
            post=True,
            company=self.company_data["company"],
        )
        wizard = self.create_send_and_print(invoice_ok + invoice_ko)
        wizard.action_send_and_print()

        invoices = (invoice_ok + invoice_ko).sudo()
        self.assertTrue(all(invoice.sending_data for invoice in invoices))

        MixinAccountMoveSend = type(self.env["mixin.account.move.send"])
        real_send_mail = MixinAccountMoveSend._send_mail

        def _send_mail_maybe_fail(self, move, *args, **kwargs):
            if move.id == invoice_ko.id:
                raise ValueError("boom")
            return real_send_mail(self, move, *args, **kwargs)

        with (
            self.enter_registry_test_mode(),
            patch.object(MixinAccountMoveSend, "_send_mail", _send_mail_maybe_fail),
            self.assertLogs(_SEND_LOGGER, "ERROR") as logs,
        ):
            self.env.ref("account.ir_cron_account_move_send").method_direct_trigger()

        self.assertEqual(len(logs.output), 1, "only the failing move is logged")
        self.assertIn(
            f"Failed sending the email for move {invoice_ko.id}", logs.output[0]
        )
        self.assertTrue(invoice_ok.invoice_pdf_report_id)
        self.assertTrue(invoice_ko.invoice_pdf_report_id)
        self.assertFalse(invoice_ok.sending_data)
        self.assertFalse(invoice_ko.sending_data)
        self.assertTrue(
            invoice_ko.message_ids.filtered(
                lambda m: "resend it manually" in (m.body or "")
            )
        )

    def test_cron_notifications(self):
        invoices_success = self.init_invoice(
            "out_invoice", amounts=[1000], post=True
        ) + self.init_invoice("out_invoice", amounts=[1000], post=True)
        invoices_error = self.init_invoice(
            "out_invoice", amounts=[1000], post=True
        ) + self.init_invoice("out_invoice", amounts=[1000], post=True)

        sp_partner_1 = self.env.user.partner_id
        wizard_partner_1 = self.create_send_and_print(invoices_success)
        wizard_partner_1.action_send_and_print()

        sp_partner_2 = self.env["res.partner"].create(
            {"name": "Partner 2", "email": "test@test.odoo.com"}
        )
        self.env.user.partner_id = sp_partner_2
        wizard_partner_2 = self.create_send_and_print(invoices_error)
        wizard_partner_2.action_send_and_print()

        def _hook_invoice_document_before_pdf_report_render(
            self, invoice, invoice_data
        ):
            if invoice.id in invoices_error.ids:
                invoice_data["error"] = {"error_title": "blblblbl"}

        self.assertTrue(
            all(invoice.sending_data for invoice in invoices_success + invoices_error)
        )
        self.assertTrue(
            all(
                invoice.sending_data.get("author_partner_id") == sp_partner_1.id
                for invoice in invoices_success
            )
        )
        self.assertTrue(
            all(
                invoice.sending_data.get("author_partner_id") == sp_partner_2.id
                for invoice in invoices_error
            )
        )

        self.env.cr.precommit.run()
        self.env["bus.bus"].sudo().search([]).unlink()

        with (
            patch(
                "odoo.addons.account.models.mixin_account_move_send.MixinAccountMoveSend._hook_invoice_document_before_pdf_report_render",
                _hook_invoice_document_before_pdf_report_render,
            ),
            self.enter_registry_test_mode(),
        ):
            self.env.ref("account.ir_cron_account_move_send").method_direct_trigger()
            self.env.cr.precommit.run()

        bus_1 = (
            self.env["bus.bus"]
            .sudo()
            .search(
                [("channel", "like", f'"res.partner",{sp_partner_1.id}')],
                order="id desc",
                limit=1,
            )
        )
        payload_1 = json.loads(bus_1.message)["payload"]
        self.assertEqual(payload_1["type"], "success")
        self.assertEqual(
            sorted(payload_1["action_button"]["res_ids"]), invoices_success.ids
        )

        bus_2 = (
            self.env["bus.bus"]
            .sudo()
            .search(
                [("channel", "like", f'"res.partner",{sp_partner_2.id}')],
                order="id desc",
                limit=1,
            )
        )
        payload_2 = json.loads(bus_2.message)["payload"]
        self.assertEqual(payload_2["type"], "warning")
        self.assertEqual(
            sorted(payload_2["action_button"]["res_ids"]), invoices_error.ids
        )

    def test_is_move_sent_state(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        self.assertFalse(invoice.is_move_sent)
        wizard = self.create_send_and_print(invoice)
        wizard.action_send_and_print()
        self.assertTrue(invoice.is_move_sent)
        invoice.action_draft()
        self.assertTrue(invoice.is_move_sent)
        pdf_report = invoice.invoice_pdf_report_id
        self.assertTrue(pdf_report)
        invoice.invoice_pdf_report_id.unlink()
        self.assertTrue(invoice.is_move_sent)

    def test_no_sending_method_selected(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        self.assertFalse(invoice.invoice_pdf_report_id)
        wizard = self.create_send_and_print(invoice, sending_methods=[])
        self.assertFalse(wizard.sending_methods)
        wizard.action_send_and_print()
        self.assertTrue(invoice.is_move_sent)
        self.assertTrue(invoice.invoice_pdf_report_id)

    def test_get_sending_settings(self):
        invoice = self.init_invoice("out_invoice", amounts=[1000], post=True)
        wizard = self.create_send_and_print(invoice, sending_methods=["email"])

        expected_results = {
            "sending_methods": ["email"],
            "invoice_edi_format": False,
            "extra_edis": [],
            "pdf_report": self.env.ref("account.account_invoices"),
            "author_user_id": self.env.user.id,
            "author_partner_id": self.env.user.partner_id.id,
            "mail_template": self.env.ref("account.email_template_edi_invoice"),
            "mail_lang": "en_US",
            "mail_body": wizard.body,
            "mail_subject": "company_1_data Invoice (Ref INV/2019/00001)",
            "mail_partner_ids": invoice.partner_id.ids,
            "mail_attachments_widget": [
                {
                    "id": "placeholder_INV_2019_00001.pdf",
                    "name": "INV_2019_00001.pdf",
                    "mimetype": "application/pdf",
                    "placeholder": True,
                }
            ],
        }
        results = wizard._get_sending_settings()
        self.assertDictEqual(results, expected_results)

    def test_pdf_report_id(self):
        invoice = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[300], post=True
        )
        default_report = invoice._get_available_invoice_template_pdf_report_ids()[0]
        wizard = self.create_send_and_print(invoice)
        self.assertEqual(default_report, wizard.pdf_report_id)

        second_report = self.env["ir.actions.report"].create(
            {
                "name": "Second report",
                "model": "account.move",
                "report_name": "test_account_move_send.second_report",
                "is_invoice_report": True,
            }
        )
        wizard = self.create_send_and_print(invoice)
        self.assertEqual(default_report, wizard.pdf_report_id)
        self.partner_a.invoice_template_pdf_report_id = second_report
        wizard = self.create_send_and_print(invoice)
        self.assertEqual(second_report, wizard.pdf_report_id)

        third_report = self.env["ir.actions.report"].create(
            {
                "name": "Third report",
                "model": "account.move",
                "report_name": "test_account_move_send.third_report",
                "is_invoice_report": True,
            }
        )
        self.company_data[
            "default_journal_sale"
        ].invoice_template_pdf_report_id = third_report
        invoice2 = self.init_invoice(
            "out_invoice", partner=self.partner_b, post=True, amounts=[1000]
        )
        wizard = self.create_send_and_print(invoice2)
        self.assertEqual(third_report, wizard.pdf_report_id)

        invoice3 = self.init_invoice(
            "out_invoice", partner=self.partner_a, post=True, amounts=[300]
        )
        wizard = self.create_send_and_print(invoice3)
        self.assertEqual(second_report, wizard.pdf_report_id)

    def test_invoice_email_subtitle(self):
        partner = self.env["res.partner"].create(
            {"type": "invoice", "parent_id": self.partner_a.id}
        )
        invoice = self.init_invoice(
            "out_invoice", amounts=[1000], partner=partner, post=True
        )
        context = invoice._notify_by_email_prepare_rendering_context(
            message=self.env["mail.message"]
        )
        self.assertEqual(context.get("subtitles")[0], invoice.name)

        invoice.partner_id.name = "Test Partner"
        context = invoice._notify_by_email_prepare_rendering_context(
            message=self.env["mail.message"]
        )
        self.assertEqual(context.get("subtitles")[0], f"{invoice.name} - Test Partner")

    def test_get_invoice_report_filename(self):
        mock_template = self.env.ref("account.account_invoices_without_payment")
        mock_template.write(
            {
                "is_invoice_report": True,
                "print_report_name": "('CustomName_%s' % (object._get_report_base_filename()))",
            }
        )
        move = self.init_invoice(
            "out_invoice", amounts=[1000], partner=self.partner_a, post=True
        )
        wizard_1 = self.create_send_and_print(move)
        wizard_1.action_send_and_print()
        self.assertEqual(
            move.message_main_attachment_id.name,
            f"{move._get_report_base_filename().replace('/', '_')}.pdf",
        )

        self.partner_a.invoice_template_pdf_report_id = mock_template.id
        move2 = self.init_invoice(
            "out_invoice", amounts=[1000], partner=self.partner_a, post=True
        )
        wizard_2 = self.create_send_and_print(move2)
        wizard_2.action_send_and_print()
        self.assertEqual(
            move2.message_main_attachment_id.name,
            f"CustomName_{move2._get_report_base_filename().replace('/', '_')}.pdf",
        )

    def test_journal_follower_gets_pdf_on_send_and_print(self):
        watcher_email = "watcher@example.com; bob@example.com"
        journal = self.company_data["default_journal_sale"]
        journal.incoming_einvoice_notification_email = watcher_email

        invoice = self.init_invoice(
            "out_invoice", amounts=[1000], partner=self.partner_a, post=True
        )
        wizard = self.create_send_and_print(invoice)

        with patch(
            "odoo.addons.mail.models.mail_template.MailTemplate.send_mail"
        ) as patched_send_mail:
            wizard.action_send_and_print()

        self.assertEqual(patched_send_mail.call_count, 2)

        for call in patched_send_mail.call_args_list:
            attachments_data = call.kwargs.get("email_values", {}).get(
                "attachment_ids", []
            )
            self.assertTrue(invoice.invoice_pdf_report_id)
            self.assertEqual(len(attachments_data), 1)
            self.assertRecordValues(
                invoice.invoice_pdf_report_id,
                [
                    {
                        "name": attachments_data[0][2]["name"],
                        "raw": attachments_data[0][2]["raw"],
                    }
                ],
            )

    def test_check_move_constraints_reports_every_violation(self):
        draft_move_a = self.init_invoice("out_invoice", post=False)
        draft_move_b = self.init_invoice("out_invoice", post=False)
        with self.assertRaises(UserError) as capture:
            self.env["mixin.account.move.send"]._check_move_constraints(
                draft_move_a + draft_move_b
            )
        self.assertIn(draft_move_a.display_name, str(capture.exception))
        self.assertIn(draft_move_b.display_name, str(capture.exception))
