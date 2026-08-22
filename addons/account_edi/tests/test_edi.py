# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged

from odoo.addons.account_edi.tests.common import AccountEdiTestCommon
from odoo.addons.base.tests.test_ir_cron import CronMixinCase


@tagged("post_install", "-at_install")
class TestAccountEdi(AccountEdiTestCommon, CronMixinCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env["account.edi.document"].search([]).unlink()
        cls.env["account.edi.format"].search([]).unlink()

        cls.test_edi_format = (
            cls.env["account.edi.format"]
            .sudo()
            .create(
                {
                    "name": "test_edi_format",
                    "code": "test_edi_format",
                }
            )
        )
        cls.company_data["default_journal_sale"].edi_format_ids |= cls.test_edi_format

    def test_export_edi(self):
        invoice = self.init_invoice("out_invoice", products=self.product_a)

        self.assertEqual(len(invoice.edi_document_ids), 0)
        with (
            self.with_custom_method(
                "_get_move_applicability",
                lambda edi_format, inv: {"post": edi_format._test_edi_post_invoice},
            ),
            self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ),
        ):
            invoice.action_post()
        self.assertEqual(len(invoice.edi_document_ids), 1)

    def test_prepare_jobs_no_batching(self):
        invoice1 = self.init_invoice("out_invoice", products=self.product_a)
        invoice2 = self.init_invoice("out_invoice", products=self.product_a)

        with (
            self.with_custom_method(
                "_get_move_applicability",
                lambda edi_format, inv: {"post": edi_format._test_edi_post_invoice},
            ),
            self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ),
            self.with_custom_method("_needs_web_services", lambda edi_format: True),
        ):
            (invoice1 + invoice2).action_post()

            jobs = (invoice1 + invoice2).edi_document_ids._prepare_jobs()
            self.assertEqual(len(jobs), 2)

    def test_prepare_jobs_batching(self):
        invoice1 = self.init_invoice("out_invoice", products=self.product_a)
        invoice2 = self.init_invoice("out_invoice", products=self.product_a)

        with (
            self.with_custom_method(
                "_get_move_applicability",
                lambda edi_format, inv: {
                    "post": edi_format._test_edi_post_invoice,
                    "post_batching": lambda inv: (inv.partner_id,),
                },
            ),
            self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ),
            self.with_custom_method("_needs_web_services", lambda edi_format: True),
        ):
            (invoice1 + invoice2).action_post()

            jobs = (invoice1 + invoice2).edi_document_ids._prepare_jobs()
            self.assertEqual(len(jobs), 1)

    def test_warning_is_retried(self):
        invoice = self.init_invoice("out_invoice", products=self.product_a)

        with (
            self.with_custom_method(
                "_get_move_applicability",
                lambda edi_format, inv: {"post": edi_format._test_edi_post_invoice},
            ),
            self.with_custom_method("_needs_web_services", lambda edi_format: True),
        ):
            with self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {
                    inv: {"error": "turlututu", "blocking_level": "warning"}
                },
            ):
                invoice.action_post()
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "to_send"}])

            with self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ):
                invoice.action_process_edi_web_services(with_commit=False)
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "sent"}])

    def test_edi_flow(self):
        invoice = self.init_invoice("out_invoice", products=self.product_a)

        with (
            self.with_custom_method(
                "_get_move_applicability",
                lambda edi_format, inv: {
                    "post": edi_format._test_edi_post_invoice,
                    "cancel": edi_format._test_edi_cancel_invoice,
                },
            ),
            self.with_custom_method("_needs_web_services", lambda edi_format: True),
            self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ),
            self.with_custom_method(
                "_test_edi_cancel_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ),
        ):
            invoice.action_post()
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "to_send"}])

            invoice.action_process_edi_web_services(with_commit=False)
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "sent"}])

            invoice.button_cancel_posted_moves()
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "to_cancel"}])

            invoice.button_abandon_cancel_posted_posted_moves()
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "sent"}])

            invoice.button_cancel_posted_moves()
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "to_cancel"}])

            invoice.action_process_edi_web_services(with_commit=False)
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "cancelled"}])

    def test_edi_flow_two_steps(self):
        def step1(edi_format, invoice):
            return {invoice: {"error": "step1 done", "blocking_level": "info"}}

        def step2(edi_format, invoice):
            return {invoice: {"success": True}}

        def get_move_applicability(edi_format, invoice):
            if "step1" in (invoice.edi_document_ids.error or ""):
                return {"post": edi_format._test_edi_post_invoice_step2}
            else:
                return {"post": edi_format._test_edi_post_invoice_step1}

        invoice = self.init_invoice("out_invoice", products=self.product_a)

        with (
            self.with_custom_method("_get_move_applicability", get_move_applicability),
            self.with_custom_method("_needs_web_services", lambda edi_format: True),
            self.with_custom_method("_test_edi_post_invoice_step1", step1),
            self.with_custom_method("_test_edi_post_invoice_step2", step2),
        ):
            invoice.action_post()
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "to_send"}])

            invoice.action_process_edi_web_services(with_commit=False)
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "to_send"}])

            invoice.action_process_edi_web_services(with_commit=False)
            self.assertRecordValues(invoice.edi_document_ids, [{"state": "sent"}])

    def test_cron_triggers(self):
        invoice = self.init_invoice("out_invoice", products=self.product_a)
        with (
            self.with_custom_method(
                "_get_move_applicability",
                lambda edi_format, inv: {"post": edi_format._test_edi_post_invoice},
            ),
            self.with_custom_method("_needs_web_services", lambda edi_format: True),
            self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ),
            self.capture_triggers("account_edi.ir_cron_edi_network") as capt,
        ):
            invoice.action_post()
            capt.records.ensure_one()

    def test_cron_self_trigger(self):
        # Process single job by CRON call (and thus, disable the auto-commit).
        edi_cron = self.env.ref("account_edi.ir_cron_edi_network")
        edi_cron.code = "model._cron_process_documents_web_services(job_count=1)"

        invoice1 = self.init_invoice("out_invoice", products=self.product_a)
        invoice2 = self.init_invoice("out_invoice", products=self.product_a)
        with (
            self.with_custom_method(
                "_get_move_applicability",
                lambda edi_format, inv: {"post": edi_format._test_edi_post_invoice},
            ),
            self.with_custom_method("_needs_web_services", lambda edi_format: True),
            self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ),
            self.enter_registry_test_mode(),
        ):
            # One capture per action, never one spanning both. 'method_direct_trigger'
            # processes the job exactly the way a worker does, and a worker consumes
            # the triggers that woke it: '_remove_triggers_due' deletes every pending
            # trigger of the cron BEFORE running the callback. A capture spanning both
            # actions would therefore see the posting trigger deleted under it and
            # count only the re-trigger.
            with self.capture_triggers("account_edi.ir_cron_edi_network") as capt_post:
                (invoice1 + invoice2).action_post()
            capt_post.records.ensure_one()

            with self.capture_triggers("account_edi.ir_cron_edi_network") as capt_cron:
                self.env.ref("account_edi.ir_cron_edi_network").method_direct_trigger()
            self.assertEqual(
                len(capt_cron.records),
                1,
                "Only one of the two jobs ran, so the cron should re-trigger itself to"
                " process the remaining one later",
            )

    def test_invoice_ready_to_be_sent(self):
        invoice = self.init_invoice("out_invoice", products=self.product_a)
        with (
            self.with_custom_method(
                "_get_move_applicability",
                lambda edi_format, inv: {"post": edi_format._test_edi_post_invoice},
            ),
            self.with_custom_method("_needs_web_services", lambda edi_format: True),
            self.with_custom_method(
                "_test_edi_post_invoice",
                lambda edi_format, inv: {inv: {"success": True}},
            ),
        ):
            invoice.action_post()
            self.assertFalse(invoice._is_ready_to_be_sent())
            invoice.action_process_edi_web_services(with_commit=False)
            self.assertTrue(invoice._is_ready_to_be_sent())
