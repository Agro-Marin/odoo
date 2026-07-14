# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json

from odoo import http
from odoo.fields import Command
from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProductDocumentUpload(HttpCase):
    """Exercise /product/document/upload end to end, including the
    record-rule (multi-company) enforcement on the target record."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Company B"})
        cls.user = new_test_user(
            cls.env,
            login="doc_uploader",
            groups="base.group_user,product.group_product_manager",
            company_id=cls.company_a.id,
            company_ids=[Command.set(cls.company_a.ids)],
        )
        cls.product_a = cls.env["product.template"].create(
            {"name": "Product A", "company_id": cls.company_a.id}
        )
        cls.product_b = (
            cls.env["product.template"]
            .with_company(cls.company_b)
            .create({"name": "Product B", "company_id": cls.company_b.id})
        )

    def _upload(self, res_model, res_id):
        self.authenticate("doc_uploader", "doc_uploader")
        response = self.url_open(
            "/product/document/upload",
            data={
                "res_model": res_model,
                "res_id": res_id,
                "csrf_token": http.Request.csrf_token(self),
            },
            files={"ufile": ("test.txt", b"content", "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def _documents_of(self, record):
        return self.env["product.document"].sudo().search(
            [("res_model", "=", record._name), ("res_id", "=", record.id)]
        )

    def test_upload_own_company_product(self):
        result = self._upload("product.template", self.product_a.id)
        self.assertIn("success", result)
        document = self._documents_of(self.product_a)
        self.assertEqual(len(document), 1)
        self.assertEqual(document.name, "test.txt")
        self.assertEqual(document.mimetype, "text/plain")
        self.assertEqual(document.company_id, self.company_a)

    def test_upload_other_company_product_denied(self):
        """The record rule must block uploads on another company's product."""
        result = self._upload("product.template", self.product_b.id)
        self.assertIn("error", result)
        self.assertFalse(self._documents_of(self.product_b))

    def test_upload_invalid_model(self):
        result = self._upload("res.partner", self.env.user.partner_id.id)
        self.assertIn("error", result)

    def test_upload_invalid_res_id(self):
        result = self._upload("product.template", "not-a-number")
        self.assertIn("error", result)

    def test_upload_missing_record(self):
        result = self._upload("product.template", 999999999)
        self.assertIn("error", result)
