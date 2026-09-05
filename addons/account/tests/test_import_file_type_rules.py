from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.account.tools.import_file_type import is_pdf


@tagged("post_install", "-at_install")
class TestImportFileTypeRules(TransactionCase):
    # `post_install`: every module carrying an `_import_file_type_rules`
    # override prepends to the list, so an at-install run would read a
    # shorter chain and pass by seeing less.

    def _importers(self):
        mixin = self.env.registry["mixin.account.document.import"]
        return [
            self.env[name]
            for name in self.env.registry
            if not name.startswith("mixin.")
            and issubclass(self.env.registry[name], mixin)
        ]

    def test_every_importer_declares_well_formed_rules(self):
        importers = self._importers()
        self.assertIn("account.move", [model._name for model in importers])
        for model in importers:
            with self.subTest(model=model._name):
                rules = model._import_file_type_rules()
                self.assertTrue(rules)
                for file_type, matches in rules:
                    self.assertIsInstance(file_type, str)
                    self.assertTrue(callable(matches), file_type)
                types = [file_type for file_type, _ in rules]
                self.assertEqual(
                    len(types), len(set(types)), f"duplicated rule: {types}"
                )
                # The most generic rule is the last one asked.
                self.assertEqual(rules[-1], ("pdf", is_pdf))

    def test_the_fallback_is_pdf_by_mimetype_or_by_name(self):
        move = self.env["account.move"]
        pdf = {
            "name": "bill.pdf",
            "raw": b"%PDF",
            "mimetype": "application/pdf",
            "xml_tree": None,
        }
        named = {
            "name": "bill.pdf",
            "raw": b"",
            "mimetype": "application/octet-stream",
            "xml_tree": None,
        }
        text = {
            "name": "note.txt",
            "raw": b"hi",
            "mimetype": "text/plain",
            "xml_tree": None,
        }
        self.assertEqual(move._get_import_file_type(pdf), "pdf")
        self.assertEqual(move._get_import_file_type(named), "pdf")
        self.assertIsNone(move._get_import_file_type(text))

    def test_a_prepended_rule_is_asked_before_the_fallback(self):
        Move = self.env.registry["account.move"]
        original = Move._import_file_type_rules

        def prepended(self):
            return [("test.everything", lambda file_data: True), *original(self)]

        pdf = {
            "name": "bill.pdf",
            "raw": b"%PDF",
            "mimetype": "application/pdf",
            "xml_tree": None,
        }
        with patch.object(Move, "_import_file_type_rules", prepended):
            self.assertEqual(
                self.env["account.move"]._get_import_file_type(pdf), "test.everything"
            )
        self.assertEqual(self.env["account.move"]._get_import_file_type(pdf), "pdf")
