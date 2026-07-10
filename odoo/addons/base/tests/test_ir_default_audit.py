import json

from odoo.tests.common import TransactionCase, mute_logger, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestIrDefaultCompanyDependent(TransactionCase):
    """Regression coverage for the company-dependent helpers of ``ir.default``.

    Covers two previously-untested ORM methods (ird-T1/ird-T2):
    ``_get_field_column_fallbacks`` (per-company column fallback mapping) and
    ``_evaluate_condition_with_fallback`` (tri-state True/False/None return).
    ``res.partner.barcode`` is the reference ``company_dependent`` Char.
    """

    def setUp(self):
        super().setUp()
        self.IrDefault = self.env["ir.default"]
        # Clean slate so prior res.partner defaults don't leak into the mapping.
        self.IrDefault.search([("field_id.model", "=", "res.partner")]).unlink()
        # barcode must stay company_dependent or the methods are never exercised.
        self.assertTrue(self.env["res.partner"]._fields["barcode"].company_dependent)

    def _existing_company_ids(self):
        """Return the current ``res.company`` ids via raw SQL, mirroring what
        ``_get_field_column_fallbacks`` reads internally.
        """
        self.env.flush_all()
        self.env.cr.execute("SELECT ARRAY_AGG(id) FROM res_company")
        company_ids = self.env.cr.fetchone()[0] or []
        self.env.invalidate_all()
        return set(company_ids)

    def test_field_column_fallbacks_no_default(self):
        """With no default, every company maps to the field's null fallback."""
        result = json.loads(
            self.IrDefault._get_field_column_fallbacks("res.partner", "barcode")
        )
        company_ids = self._existing_company_ids()
        # The keys are JSON object keys, hence strings: one entry per company.
        self.assertEqual({int(cid) for cid in result}, company_ids)
        # No default + Char column-format fallback serialises to JSON null.
        self.assertTrue(all(value is None for value in result.values()))

    def test_field_column_fallbacks_with_default(self):
        """A global default is reflected as the column value for every company."""
        self.IrDefault.set(
            "res.partner", "barcode", "DEFBC", user_id=False, company_id=False
        )
        result = json.loads(
            self.IrDefault._get_field_column_fallbacks("res.partner", "barcode")
        )
        company_ids = self._existing_company_ids()
        self.assertEqual({int(cid) for cid in result}, company_ids)
        # Char column format keeps the plain string for each company.
        self.assertTrue(all(value == "DEFBC" for value in result.values()))

    def test_field_column_fallbacks_company_added(self):
        """Creating a company busts the (model, field)-keyed ormcache."""
        # Prime the ormcache with the current company set.
        first = json.loads(
            self.IrDefault._get_field_column_fallbacks("res.partner", "barcode")
        )
        new_company = self.env["res.company"].create({"name": "Audit Co"})
        # res.company.create calls registry.clear_cache(), so the cached
        # (model, field) entry must be recomputed with the new company id.
        second = json.loads(
            self.IrDefault._get_field_column_fallbacks("res.partner", "barcode")
        )
        self.assertNotIn(str(new_company.id), first)
        self.assertIn(str(new_company.id), second)
        self.assertEqual(set(first) | {str(new_company.id)}, set(second))

    @mute_logger("odoo.orm.fields")
    def test_evaluate_condition_true_and_false(self):
        """Fallback satisfying the condition returns True, otherwise False."""
        # With no default, the barcode fallback is falsy (False).
        self.assertIs(
            self.IrDefault._evaluate_condition_with_fallback(
                "res.partner", "barcode", "=", False
            ),
            True,
        )
        self.assertIs(
            self.IrDefault._evaluate_condition_with_fallback(
                "res.partner", "barcode", "!=", False
            ),
            False,
        )

    @mute_logger("odoo.orm.fields")
    def test_evaluate_condition_unknown_returns_none(self):
        """A malformed operator raises ValueError, swallowed as None (unknown)."""
        # An operator outside CONDITION_OPERATORS makes Domain() raise
        # ValueError at construction; the method catches it and returns None.
        new_test_user(self.env, login="ird_audit_user")
        self.assertIsNone(
            self.IrDefault._evaluate_condition_with_fallback(
                "res.partner", "barcode", "definitely_not_an_operator", "x"
            )
        )
