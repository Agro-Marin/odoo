import contextlib

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.document_extract.tools import FREE, BaseExtractor
from odoo.addons.document_extract.tools import extractors as registry


class _Stub(BaseExtractor):
    name = "receipt_test_stub"
    doc_types = ("receipt",)
    needs = ("text",)
    cost = FREE
    confidence = 0.9

    def __init__(self, values):
        self._values = values

    def extract(self, source, doc_type, wanted, env=None):
        return dict(self._values) if self._values else None


@contextlib.contextmanager
def _only(extractor):
    saved = dict(registry._EXTRACTORS)
    registry._EXTRACTORS.clear()
    try:
        registry.register_extractor(extractor)
        yield
    finally:
        registry._EXTRACTORS.clear()
        registry._EXTRACTORS.update(saved)


@tagged("post_install", "-at_install")
class TestExpenseExtraction(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "Grace Hopper"})
        cls.company_currency = cls.env.company.currency_id
        # hr_expense ships this one; a second EXP_GEN would shadow it.
        cls.generic = cls.env.ref("hr_expense.product_product_no_cost")

    def _expense(self, **values):
        """An expense as `create_expense_from_attachments` makes one.

        `name` is required and computes to `name or product_id.display_name`, so
        an expense with neither cannot be stored; and the upload path always
        supplies both -- an untitled name and a generic product.
        """
        vals = {
            "employee_id": self.employee.id,
            "name": self.env["hr.expense"]._get_untitled_expense_name("2026-03-01"),
            "product_id": self.generic.id,
            "price_unit": 0,
        }
        vals.update(values)
        expense = self.env["hr.expense"].create(vals)
        self.env["ir.attachment"].create(
            {
                "name": "receipt.txt",
                "res_model": "hr.expense",
                "res_id": expense.id,
                "mimetype": "text/plain",
                "raw": b"a receipt with words on it",
            }
        )
        return expense

    _READ = {"merchant_name": "Cafe Turing", "date": "2026-03-04", "total": 250.0}

    def test_it_fills_the_receipt_into_an_untouched_expense(self):
        with _only(_Stub(self._READ)):
            expense = self._expense()

            expense.action_extract_document()

        self.assertEqual(expense.name, "Cafe Turing")
        self.assertEqual(str(expense.date), "2026-03-04")
        self.assertEqual(expense.total_amount_currency, 250.0)
        self.assertEqual(expense.extract_state, "done")

    def test_it_does_not_rename_an_expense_a_person_named(self):
        with _only(_Stub(self._READ)):
            expense = self._expense(name="Client lunch, Tuesday")

            expense.action_extract_document()

        self.assertEqual(expense.name, "Client lunch, Tuesday")
        self.assertEqual(expense.total_amount_currency, 250.0)

    def test_it_does_not_move_a_date_a_person_set(self):
        with _only(_Stub(self._READ)):
            expense = self._expense(date="2026-01-31")

            expense.action_extract_document()

        self.assertEqual(str(expense.date), "2026-01-31")

    def test_a_receipt_with_no_total_leaves_the_amount_alone(self):
        with _only(_Stub({"merchant_name": "Cafe Turing", "total": 0.0})):
            expense = self._expense()

            expense.action_extract_document()

        self.assertEqual(expense.total_amount_currency, 0.0)

    def test_it_reads_the_currency_the_receipt_names(self):
        # A fresh database activates one currency; the rest exist but are not
        # searchable without active_test, and _get_extract_currency looks past
        # `active` deliberately -- a receipt names what it names.
        other = (
            self.env["res.currency"]
            .with_context(active_test=False)
            .search([("id", "!=", self.company_currency.id)], limit=1)
        )
        read = dict(self._READ, currency=other.name)

        with _only(_Stub(read)):
            expense = self._expense()

            expense.action_extract_document()

        self.assertEqual(expense.currency_id, other)
        self.assertEqual(expense.total_amount_currency, 250.0)

    def test_a_currency_it_cannot_resolve_leaves_the_currency_alone(self):
        with _only(_Stub(dict(self._READ, currency="galleons"))):
            expense = self._expense()

            expense.action_extract_document()

        self.assertEqual(expense.currency_id, self.company_currency)

    def test_a_draft_expense_can_be_read(self):
        expense = self._expense()

        self.assertEqual(expense.state, "draft")
        self.assertTrue(expense.extract_can_be_read)

    def test_reading_is_refused_once_it_is_done(self):
        with _only(_Stub(self._READ)):
            expense = self._expense()

            expense.action_extract_document()

        self.assertFalse(expense.extract_can_be_read)
        with self.assertRaises(UserError):
            expense.action_extract_document()

    def test_it_keeps_which_reader_produced_each_value(self):
        with _only(_Stub(self._READ)):
            expense = self._expense()

            expense.action_extract_document()

        self.assertEqual(
            expense.extract_result["merchant_name"]["source"], "receipt_test_stub"
        )
