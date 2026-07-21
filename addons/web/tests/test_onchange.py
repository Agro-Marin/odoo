"""Behavioral tests for the ``onchange`` engine (``web_onchange.py``).

The engine drives every form-view field change (default seeding on first call,
recomputation of dependent fields) but had no direct coverage beyond an
access-error case in ``test_partner``.
"""

from odoo.tests import common


@common.tagged("post_install", "-at_install", "web_unit", "web_onchange")
class TestOnchange(common.TransactionCase):
    def test_first_call_seeds_defaults(self):
        """Empty ``field_names`` => first call: defaults are seeded into value."""
        result = self.env["res.partner"].onchange(
            {}, [], {"name": {}, "active": {}, "company_type": {}}
        )
        self.assertIn("value", result)
        # res.partner.active defaults to True
        self.assertTrue(result["value"].get("active"))

    def test_field_change_recomputes_dependent(self):
        """Changing company_type flips the dependent is_company flag."""
        result = self.env["res.partner"].onchange(
            {"company_type": "company", "is_company": False},
            ["company_type"],
            {"company_type": {}, "is_company": {}},
        )
        self.assertIn("value", result)
        self.assertTrue(
            result["value"].get("is_company"),
            "onchange must recompute is_company from company_type",
        )

    def test_unknown_changed_field_is_dropped_not_fatal(self):
        """An unknown name among the changed fields must not void the onchange.

        A stale/cached view can still reference a field removed by a module
        upgrade. The valid changed fields must still recompute; only the unknown
        name is dropped (previously a single unknown name returned ``{}`` and
        silently stopped recomputing every valid field too).
        """
        result = self.env["res.partner"].onchange(
            {"company_type": "company", "is_company": False},
            ["company_type", "field_that_does_not_exist"],
            {"company_type": {}, "is_company": {}},
        )
        self.assertIn("value", result)
        self.assertTrue(
            result["value"].get("is_company"),
            "a valid changed field must still recompute despite an unknown name",
        )

    def test_all_unknown_changed_fields_is_noop(self):
        """If every changed field is unknown, onchange is a no-op (``{}``)."""
        result = self.env["res.partner"].onchange(
            {"company_type": "company"},
            ["field_that_does_not_exist"],
            {"company_type": {}, "is_company": {}},
        )
        self.assertEqual(result, {})

    def test_changed_field_absent_from_values_does_not_crash(self):
        """A known changed field missing from ``values`` must fail open, not 500.

        The JS changeset builder can drop a field that is still in
        ``field_names`` (a many2one awaiting ``name_create``, a non-StaticList
        x2many on the urgent/beacon path). ``changed_values`` used to
        ``pop(fname)`` without a default, raising ``KeyError`` -> 500. The
        remaining valid fields must still recompute.
        """
        result = self.env["res.partner"].onchange(
            {"company_type": "company", "is_company": False},
            # ``name`` is a valid field, is in field_names, but absent from values
            ["company_type", "name"],
            {"company_type": {}, "is_company": {}, "name": {}},
        )
        self.assertIn("value", result)
        self.assertTrue(
            result["value"].get("is_company"),
            "valid changed fields must still recompute when another changed "
            "field is absent from values",
        )
