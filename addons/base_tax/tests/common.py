"""Shared fixtures for the ``base_tax`` test suite."""

from odoo.tests import TransactionCase


class BaseTaxCommon(TransactionCase):
    """Company, country and tax-group scaffolding shared by base_tax tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # A tax needs a (non-null) country and tax group; base_tax ships
        # neither. Derive the country from the company (US only as fallback)
        # and pin it explicitly on the group: hardcoding a country breaks on
        # databases whose company already has one (the group defaults to it
        # and the country-consistency constraint rejects the mismatch).
        cls.country = cls.company.country_id or cls.env.ref("base.us")
        if not cls.company.country_id:
            cls.company.country_id = cls.country
        cls.tax_group = cls.env["account.tax.group"].create(
            {
                "name": "base_tax test group",
                "company_id": cls.company.id,
                "country_id": cls.country.id,
            }
        )
        cls.currency = cls.company.currency_id
        cls.account_installed = (
            "tax_calculation_rounding_method" in cls.env["res.company"]._fields
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    _seq = 0

    @classmethod
    def _tax(cls, amount, amount_type="percent", **kw):
        cls._seq += 1
        kw.setdefault("name", f"BT test tax {cls._seq}")
        kw.setdefault("type_tax_use", "sale")
        kw.setdefault("country_id", cls.country.id)
        kw.setdefault("tax_group_id", cls.tax_group.id)
        return cls.env["account.tax"].create(
            {"amount_type": amount_type, "amount": amount, **kw}
        )

    def _base_line(self, taxes, price_unit, quantity=1.0, **kw):
        return self.env["account.tax"]._prepare_base_line_for_taxes_computation(
            None,
            company_id=self.company,
            currency_id=self.currency,
            tax_ids=taxes,
            price_unit=price_unit,
            quantity=quantity,
            **kw,
        )
