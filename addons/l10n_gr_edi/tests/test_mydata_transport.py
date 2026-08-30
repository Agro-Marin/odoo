from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_mydata_invoice import TestMyDATAInvoice

MARK = "400001924190891"

SEAM = "odoo.addons.exchange.models.exchange_channel.ExchangeChannel._get_api_client"


def _response(*entries) -> dict:
    """A myDATA ResponseDoc, in the shape the authority actually answers with."""
    body = ["<ResponseDoc>"]
    for index, entry in enumerate(entries, start=1):
        body.append(f"<response><index>{index}</index>")
        if "error" in entry:
            body.append(
                "<statusCode>ValidationError</statusCode><errors><error>"
                f"<code>{entry.get('code', '204')}</code>"
                f"<message>{entry['error']}</message>"
                "</error></errors>"
            )
        else:
            body.append("<statusCode>Success</statusCode>")
            body.append(f"<invoiceMark>{entry['mark']}</invoiceMark>")
            if cls_mark := entry.get("cls_mark"):
                body.append(f"<classificationMark>{cls_mark}</classificationMark>")
            body.append(f"<qrUrl>{entry.get('url', 'https://mydata/qr')}</qrUrl>")
        body.append("</response>")
    body.append("</ResponseDoc>")
    return {"body": "".join(body), "status_code": 200}


@tagged("post_install_l10n", "post_install", "-at_install")
class TestMyDATATransport(TestMyDATAInvoice):
    """What the XML-fixture suite does not reach: the conversation itself.

    Every test here drives `exchange` through the myDATA protocol with the HTTP
    client mocked at the channel, so it exercises the batching, the per-index
    verdicts and the retry that porting this module onto exchange introduced.
    """

    def _invoice(self):
        return self._create_mydata_invoice(
            invoice_line_ids=[
                Command.create(
                    {
                        "product_id": self.product_a.id,
                        "tax_ids": [Command.set(self.tax_24.ids)],
                        "l10n_gr_edi_cls_category": "category1_1",
                        "l10n_gr_edi_cls_type": "E3_561_001",
                    }
                )
            ],
        )

    def test_an_accepted_invoice_carries_the_authoritys_mark(self):
        invoice = self._invoice()
        with patch(SEAM) as client:
            client.return_value.post.return_value = _response(
                {"mark": "400001", "url": "https://mydata/qr/1"}
            )
            invoice.l10n_gr_edi_try_send_invoices()

        invoice.invalidate_recordset()
        transmission = invoice._l10n_gr_edi_get_transmission("invoice")
        self.assertEqual(transmission.state, "accepted")
        self.assertEqual(transmission.reference, "400001")
        self.assertEqual(transmission.document_kind, "mydata.invoice")
        self.assertEqual(invoice.l10n_gr_edi_state, "invoice_sent")
        self.assertEqual(invoice.l10n_gr_edi_mark, "400001")
        self.assertEqual(invoice.l10n_gr_edi_url, "https://mydata/qr/1")

    def test_what_was_sent_is_kept(self):
        invoice = self._invoice()
        with patch(SEAM) as client:
            client.return_value.post.return_value = _response({"mark": "400002"})
            invoice.l10n_gr_edi_try_send_invoices()

        transmission = invoice._l10n_gr_edi_get_transmission("invoice")
        self.assertTrue(transmission.attachment_id)
        self.assertIn(b"<InvoicesDoc", transmission.attachment_id.raw)
        self.assertIn(
            b"<vatNumber>047747270</vatNumber>", transmission.attachment_id.raw
        )

    def test_a_refusal_keeps_the_authoritys_words(self):
        invoice = self._invoice()
        with patch(SEAM) as client:
            client.return_value.post.return_value = _response(
                {"error": "Invalid VAT number", "code": "213"}
            )
            invoice.l10n_gr_edi_try_send_invoices()

        invoice.invalidate_recordset()
        transmission = invoice._l10n_gr_edi_get_transmission("invoice")
        self.assertEqual(transmission.state, "rejected")
        self.assertIn("[213] Invalid VAT number.", transmission.message)
        self.assertFalse(invoice.l10n_gr_edi_state)

    def test_two_invoices_go_in_one_call_and_settle_separately(self):
        first = self._invoice()
        second = self._invoice()
        with patch(SEAM) as client:
            client.return_value.post.return_value = _response(
                {"mark": "400003"},
                {"error": "Line 1 has no classification"},
            )
            (first + second).l10n_gr_edi_try_send_invoices()
            self.assertEqual(
                client.return_value.post.call_count,
                1,
                "myDATA takes a document list; two invoices are one request",
            )

        (first + second).invalidate_recordset()
        self.assertEqual(
            first._l10n_gr_edi_get_transmission("invoice").state, "accepted"
        )
        self.assertEqual(
            second._l10n_gr_edi_get_transmission("invoice").state, "rejected"
        )
        self.assertEqual(first.l10n_gr_edi_state, "invoice_sent")
        self.assertFalse(second.l10n_gr_edi_state)

    def test_a_transport_failure_is_retried_rather_than_lost(self):
        invoice = self._invoice()
        with (
            patch(SEAM) as client,
            mute_logger("odoo.addons.exchange.models.exchange_transmission"),
        ):
            client.return_value.post.side_effect = ConnectionError("aade unreachable")
            invoice.l10n_gr_edi_try_send_invoices()

        transmission = invoice._l10n_gr_edi_get_transmission("invoice")
        self.assertEqual(
            transmission.state,
            "queued",
            "before this module moved onto exchange a failed call left an error "
            "document and no way back",
        )
        self.assertEqual(transmission.retry_count, 1)
        self.assertTrue(transmission.date_next_retry)

    def test_a_fetched_bill_carries_a_draft_classification(self):
        bill = self._create_mydata_bill()
        transmission = bill._l10n_gr_edi_get_transmission("classification")
        self.assertEqual(transmission.state, "draft")
        self.assertEqual(transmission.l10n_gr_edi_mark, MARK)
        self.assertEqual(bill.l10n_gr_edi_state, "bill_fetched")
        self.assertEqual(bill.l10n_gr_edi_mark, MARK)

    def test_classifying_a_fetched_bill_settles_its_own_draft(self):
        bill = self._create_mydata_bill()
        opened = bill._l10n_gr_edi_get_transmission("classification")
        with patch(SEAM) as client:
            client.return_value.post.return_value = _response(
                {"mark": MARK, "cls_mark": "77770000"}
            )
            bill.l10n_gr_edi_try_send_expense_classification()

        bill.invalidate_recordset()
        transmission = bill._l10n_gr_edi_get_transmission("classification")
        self.assertEqual(
            transmission,
            opened,
            "the draft the receipt opened is the one that gets sent, not a second row",
        )
        self.assertEqual(transmission.state, "accepted")
        self.assertEqual(transmission.reference, "77770000")
        self.assertEqual(bill.l10n_gr_edi_state, "bill_sent")
        self.assertEqual(bill.l10n_gr_edi_cls_mark, "77770000")

    def test_an_invoice_and_a_classification_never_share_a_call(self):
        invoice = self._invoice()
        bill = self._create_mydata_bill()
        with patch(SEAM) as client:
            client.return_value.post.return_value = _response({"mark": "400004"})
            invoice.l10n_gr_edi_try_send_invoices()
            bill.l10n_gr_edi_try_send_expense_classification()
            endpoints = [
                call.args[0] for call in client.return_value.post.call_args_list
            ]

        self.assertEqual(endpoints, ["SendInvoices", "SendExpensesClassification"])

    def test_a_resend_is_a_second_ask_not_an_edit_of_the_first(self):
        invoice = self._invoice()
        with patch(SEAM) as client:
            client.return_value.post.return_value = _response(
                {"error": "Temporary refusal"}
            )
            invoice.l10n_gr_edi_try_send_invoices()
            first = invoice._l10n_gr_edi_get_transmission("invoice")

            client.return_value.post.return_value = _response({"mark": "400005"})
            invoice.l10n_gr_edi_try_send_invoices()

        invoice.invalidate_recordset()
        transmissions = invoice.transmission_ids.filtered(
            lambda transmission: transmission.document_kind == "mydata.invoice"
        )
        self.assertEqual(len(transmissions), 2, "the refusal is still on the record")
        self.assertEqual(first.state, "rejected")
        self.assertEqual(invoice.l10n_gr_edi_state, "invoice_sent")

    def _inbox(self, *invoices) -> dict:
        """A RequestDocs body, in the shape myDATA answers a fetch with."""
        body = ['<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">']
        body.extend(
            (
                "<invoice>"
                f"<mark>{invoice['mark']}</mark>"
                "<issuer>"
                f"<vatNumber>{invoice.get('vat', '047747210')}</vatNumber>"
                "</issuer>"
                "<invoiceHeader>"
                f"<issueDate>{invoice.get('date', '2024-02-01')}</issueDate>"
                f"<invoiceType>{invoice.get('type', '13.1')}</invoiceType>"
                "</invoiceHeader>"
                "<invoiceDetails>"
                "<lineNumber>1</lineNumber>"
                f"<quantity>{invoice.get('qty', '2')}</quantity>"
                f"<netValue>{invoice.get('net', '200.0')}</netValue>"
                "<vatCategory>1</vatCategory>"
                "</invoiceDetails>"
                "</invoice>"
            )
            for invoice in invoices
        )
        body.append("</RequestedDoc>")
        return {"body": "".join(body), "status_code": 200}

    def _channel(self):
        return self.env["exchange.channel"].search(
            [("protocol", "=", "mydata")], limit=1
        )

    def test_reading_the_inbox_creates_a_bill_and_its_draft_classification(self):
        channel = self._channel()
        with patch(SEAM) as client:
            client.return_value.get.return_value = self._inbox({"mark": "500000001"})
            channel._read_inbox()

        bill = self.env["account.move"].search([("l10n_gr_edi_mark", "=", "500000001")])
        self.assertEqual(len(bill), 1)
        self.assertEqual(bill.move_type, "in_invoice")
        self.assertEqual(bill.state, "draft")
        self.assertEqual(bill.l10n_gr_edi_state, "bill_fetched")

        transmission = bill._l10n_gr_edi_get_transmission("classification")
        self.assertEqual(transmission.state, "draft")
        self.assertEqual(transmission.l10n_gr_edi_mark, "500000001")
        self.assertFalse(
            transmission.reference,
            "the mark is their id for their document; ours arrives when we classify",
        )

    def test_a_bill_already_fetched_is_not_created_twice(self):
        channel = self._channel()
        with patch(SEAM) as client:
            client.return_value.get.return_value = self._inbox({"mark": "500000002"})
            channel._read_inbox()
            channel._read_inbox()

        self.assertEqual(
            self.env["account.move"].search_count(
                [("l10n_gr_edi_mark", "=", "500000002")]
            ),
            1,
        )

    def test_reading_the_inbox_stamps_when_it_was_read(self):
        channel = self._channel()
        with patch(SEAM) as client:
            client.return_value.get.return_value = self._inbox()
            channel._read_inbox()
        self.assertTrue(channel.date_last_inbox)

    def test_a_fetched_line_carries_the_quantity_and_unit_price_myDATA_gave(self):
        channel = self._channel()
        with patch(SEAM) as client:
            client.return_value.get.return_value = self._inbox(
                {"mark": "500000003", "qty": "4", "net": "400.0"}
            )
            channel._read_inbox()

        bill = self.env["account.move"].search([("l10n_gr_edi_mark", "=", "500000003")])
        line = bill.invoice_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.quantity, 4)
        self.assertEqual(line.price_unit, 100)
