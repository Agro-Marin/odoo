"""Audit coverage for the language export/import transient wizards.

Pins the hardened behaviour of base.language.export.act_getfile against a
self-inflicted HTTP 500 from a malformed Model Domain (audit BLEXP-1): every
parse failure and any non-list parse result must surface as a friendly
UserError. Also guards the base.language.import format-mismatch path (the
catch-all that wraps a malformed upload in a UserError) and pins the
silent-tolerance gap on malformed PO files (BLIMP-L1, deferred to framework
tools/translate.py).
"""

import base64

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestBaseLanguageWizardsAudit(TransactionCase):
    def _make_model_export(self, domain):
        """Build a model-type base.language.export wizard for res.partner.

        :param str domain: raw value for the Model Domain char field
        :return: the transient wizard record
        :rtype: base.language.export
        """
        partner_model = self.env["ir.model"].search(
            [("model", "=", "res.partner")], limit=1
        )
        return self.env["base.language.export"].create(
            {
                "lang": "__new__",
                "format": "po",
                "export_type": "model",
                "model_id": partner_model.id,
                "domain": domain,
            }
        )

    def test_blexp1_syntax_error_domain_raises_usererror(self):
        """BLEXP-1: a domain that fails to parse (SyntaxError) raises UserError."""
        wizard = self._make_model_export("[(1,2")
        with self.assertRaises(UserError):
            wizard.act_getfile()

    def test_blexp1_type_error_domain_raises_usererror(self):
        """BLEXP-1: a domain whose evaluation raises TypeError raises UserError.

        ``{[]:1}`` parses syntactically but uses an unhashable list as a dict
        key, which makes ast.literal_eval raise TypeError; before the widened
        catch this escaped as a 500.
        """
        wizard = self._make_model_export("{[]:1}")
        with self.assertRaises(UserError):
            wizard.act_getfile()

    def test_blexp1_non_list_domain_raises_usererror(self):
        """BLEXP-1: a valid literal that is not a list (e.g. ``42``) raises UserError."""
        wizard = self._make_model_export("42")
        with self.assertRaises(UserError):
            wizard.act_getfile()

    def test_blexp_happy_path_empty_domain_produces_file(self):
        """BLEXP-1: a valid empty-list domain completes the export after the fix.

        A new-language template export of a model legitimately yields no
        ``data`` (there are no record-level translations for the new lang yet),
        so the smoke test asserts the export path completed -- state moved to
        ``get`` and the output file was named -- not that bytes were produced.
        """
        wizard = self._make_model_export("[]")
        wizard.act_getfile()
        self.assertEqual(wizard.state, "get")
        self.assertTrue(wizard.name)

    def test_blimp_unsupported_format_raises_usererror(self):
        """BLIMP: an unsupported file extension surfaces as a format-mismatch UserError.

        An unsupported extension makes ``translation_file_reader`` raise a plain
        ``Exception("Bad file format")`` (tools/translate.py) -- not an
        ``OSError`` -- so it escapes ``TranslationImporter.load``'s OSError catch
        and propagates to the wizard's ``except Exception -> UserError`` guard.
        This is the reliably reachable error path for the wizard.
        """
        admin = new_test_user(
            self.env,
            login="blimp_audit_user",
            groups="base.group_system",
        )
        wizard = (
            self.env["base.language.import"]
            .with_user(admin)
            .create(
                {
                    "name": "Test Lang",
                    "code": "xx_XX",
                    "filename": "x.txt",
                    "data": base64.b64encode(b"irrelevant content"),
                }
            )
        )
        with self.assertRaises(UserError) as cm:
            wizard.import_lang()
        self.assertIn("format mismatch", str(cm.exception))

    def test_blimp_malformed_po_is_silently_tolerated(self):
        """BLIMP-L1 (deferred): a malformed .PO is swallowed, not surfaced.

        ``TranslationImporter.load`` catches ``OSError`` (which a PO syntax
        error raises) and only logs it, so ``import_lang`` returns True and the
        UI reports success while nothing was imported. This pins the current --
        imperfect -- silent-failure behaviour; the proper fix (surface the parse
        error) belongs in framework ``tools/translate.py`` and is tracked as
        deferred cross-cutting debt (BLIMP-L1), out of this wizard's scope.
        """
        admin = new_test_user(
            self.env,
            login="blimp_po_user",
            groups="base.group_system",
        )
        wizard = (
            self.env["base.language.import"]
            .with_user(admin)
            .create(
                {
                    "name": "Test Lang",
                    "code": "xx_XX",
                    "filename": "x.po",
                    "data": base64.b64encode(b"this is not a valid po file"),
                }
            )
        )
        # No exception: the OSError from the PO parser is swallowed upstream.
        self.assertTrue(wizard.import_lang())
