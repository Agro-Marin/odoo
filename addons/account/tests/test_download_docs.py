from io import BytesIO
from zipfile import ZipFile

from odoo.fields import Command
from odoo.tests.common import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingHttpCommon


@tagged("post_install", "-at_install")
class TestDownloadDocs(AccountTestInvoicingHttpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        invoice_1 = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": cls.partner_a.id,
                "invoice_line_ids": [Command.create({"price_unit": 100})],
                "attachment_ids": [
                    Command.create(
                        {
                            "name": "Attachment",
                            "mimetype": "text/plain",
                            "res_model": "account.move",
                            "datas": "test",
                        }
                    )
                ],
            }
        )
        invoice_2 = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": cls.partner_a.id,
                "invoice_line_ids": [Command.create({"price_unit": 200})],
            }
        )
        cls.invoices = invoice_1 + invoice_2
        cls.invoices.action_post()
        cls.invoices._generate_and_send()
        assert invoice_1.invoice_pdf_report_id and invoice_2.invoice_pdf_report_id

    def test_download_invoice_attachments_not_auth(self):
        url = f"/account/download_invoice_attachments/{','.join(map(str, self.invoices.invoice_pdf_report_id.ids))}"
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "oe_login_form",
            res.content.decode("utf-8"),
            "When not authenticated, the download is not possible.",
        )

    def test_download_invoice_attachments_one(self):
        attachment = self.invoices[0].invoice_pdf_report_id
        url = f"/account/download_invoice_attachments/{attachment.id}"
        self.authenticate(self.env.user.login, self.env.user.login)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, attachment.raw)

    def test_download_invoice_attachments_multiple(self):
        attachments = self.invoices.invoice_pdf_report_id
        url = f"/account/download_invoice_attachments/{','.join(map(str, attachments.ids))}"
        self.authenticate(self.env.user.login, self.env.user.login)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        with ZipFile(BytesIO(res.content)) as zip_file:
            self.assertEqual(
                zip_file.namelist(),
                self.invoices.invoice_pdf_report_id.mapped("name"),
            )

    def test_download_invoice_documents_filetype_one(self):
        url = f"/account/download_invoice_documents/{self.invoices[0].id}/pdf"
        self.authenticate(self.env.user.login, self.env.user.login)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, self.invoices[0].invoice_pdf_report_id.raw)

    def test_download_invoice_documents_filetype_multiple(self):
        url = f"/account/download_invoice_documents/{','.join(map(str, self.invoices.ids))}/pdf"
        self.authenticate(self.env.user.login, self.env.user.login)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        with ZipFile(BytesIO(res.content)) as zip_file:
            self.assertEqual(
                zip_file.namelist(),
                self.invoices.invoice_pdf_report_id.mapped("name"),
            )

    def test_download_invoice_documents_filetype_all(self):
        self.authenticate(self.env.user.login, self.env.user.login)
        url = f"/account/download_invoice_documents/{','.join(map(str, self.invoices.ids))}/all"
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        with ZipFile(BytesIO(res.content)) as zip_file:
            file_names = zip_file.namelist()
            self.assertEqual(len(file_names), 2)
            self.assertTrue(self.invoices[0].invoice_pdf_report_id.name in file_names)
            self.assertTrue(self.invoices[1].invoice_pdf_report_id.name in file_names)

    def test_download_moves_attachments(self):
        self.authenticate(self.env.user.login, self.env.user.login)
        url = f"/account/download_move_attachments/{','.join(map(str, self.invoices.ids))}"
        attachment_names = sorted(
            [
                doc["filename"]
                for invoice in self.invoices
                for doc in invoice._get_invoice_legal_documents_all()
            ]
        )
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        with ZipFile(BytesIO(res.content)) as zip_file:
            file_names = sorted(zip_file.namelist())
            self.assertEqual(file_names, attachment_names)

    def test_download_moves_attachments_with_bills(self):
        bill = self.init_invoice("in_invoice", products=self.product_a, post=True)
        bill.message_main_attachment_id = self.env["ir.attachment"].create(
            {
                "name": "Attachment",
                "mimetype": "text/plain",
                "res_model": "account.move",
                "datas": "test_bill",
            }
        )
        attachment_names = [bill.name.replace("/", "_")]
        self.authenticate(self.env.user.login, self.env.user.login)
        url = f"/account/download_move_attachments/{bill.id}"
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        with ZipFile(BytesIO(res.content)) as zip_file:
            file_names = sorted(zip_file.namelist())
            self.assertEqual(file_names, attachment_names)

    def test_download_moves_attachments_named_after_each_move(self):
        """Vendors all call their file "Attachment"/"factura.pdf", so a multi-bill
        export used to be a bag of `Attachment`, `Attachment (1)`, `Attachment (2)`
        with nothing tying a file back to the bill it documents. Each member is now
        named after its own move, and the collision disappears with it."""
        bill_1 = self.init_invoice("in_invoice", products=self.product_a, post=True)
        bill_2 = self.init_invoice("in_invoice", products=self.product_a, post=True)
        bill_3 = self.init_invoice("in_invoice", products=self.product_a, post=True)
        for bill, name in (
            (bill_1, "Attachment"),
            (bill_2, "Attachment"),
            (bill_3, "Attachment (1)"),
        ):
            bill.message_main_attachment_id = self.env["ir.attachment"].create(
                {
                    "name": name,
                    "mimetype": "text/plain",
                    "res_model": "account.move",
                    "datas": "test_bill",
                }
            )
        bills = bill_1 + bill_2 + bill_3
        self.authenticate(self.env.user.login, self.env.user.login)

        url = f"/account/download_move_attachments/{','.join(map(str, bills.ids))}"
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        with ZipFile(BytesIO(res.content)) as zip_file:
            self.assertEqual(
                sorted(zip_file.namelist()),
                sorted(bill.name.replace("/", "_") for bill in bills),
            )

    def test_download_moves_attachments_keeps_the_extension(self):
        """The move name replaces the stem only; the extension has to survive or
        the file will not open."""
        bill = self.init_invoice("in_invoice", products=self.product_a, post=True)
        bill.message_main_attachment_id = self.env["ir.attachment"].create(
            {
                "name": "factura.pdf",
                "mimetype": "application/pdf",
                "res_model": "account.move",
                "datas": "test_bill",
            }
        )
        self.authenticate(self.env.user.login, self.env.user.login)
        res = self.url_open(f"/account/download_move_attachments/{bill.id}")
        with ZipFile(BytesIO(res.content)) as zip_file:
            self.assertEqual(
                zip_file.namelist(), [f"{bill.name.replace('/', '_')}.pdf"]
            )

    def test_download_moves_attachments_zip_named_by_document_type(self):
        """The archive itself said "Invoices.zip" whatever it held. It now says
        what kind of document is inside."""
        bill = self.init_invoice("in_invoice", products=self.product_a, post=True)
        bill.message_main_attachment_id = self.env["ir.attachment"].create(
            {
                "name": "factura.pdf",
                "mimetype": "application/pdf",
                "res_model": "account.move",
                "datas": "test_bill",
            }
        )
        self.authenticate(self.env.user.login, self.env.user.login)

        res = self.url_open(f"/account/download_move_attachments/{bill.id}")
        self.assertIn("VendorBills.zip", res.headers["Content-Disposition"])

        url = f"/account/download_move_attachments/{','.join(map(str, self.invoices.ids))}"
        res = self.url_open(url)
        self.assertIn("CustomerInvoices.zip", res.headers["Content-Disposition"])

        url = f"/account/download_move_attachments/{bill.id},{self.invoices[0].id}"
        res = self.url_open(url)
        self.assertIn("Documents.zip", res.headers["Content-Disposition"])
