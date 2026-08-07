from odoo import _, api, models


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._activate_or_create_pricelists()
        return companies

    def write(self, vals):
        """Delay the automatic creation of pricelists post-company update.

        This makes sure that the pricelist(s) automatically created are created with the right
        currency.
        """
        if not vals.get("currency_id"):
            return super().write(vals)

        enabled_pricelists = self.env.user.has_group("product.group_product_pricelist")
        res = super(
            ResCompany, self.with_context(disable_company_pricelist_creation=True)
        ).write(vals)

        # Restate the auto-created default pricelist in the company's new
        # currency. It is identified exactly as `_activate_or_create_pricelists`
        # identifies it -- a pricelist of this company carrying no rule -- so a
        # pricelist an admin has actually configured (which has rules, and whose
        # currency is a deliberate business choice) is never touched.
        #
        # Leaving it behind was not merely cosmetic: that method then no longer
        # recognises it (it matches on `currency_id == company_id.currency_id`)
        # and creates a *second* pricelist named "Default" for the same company
        # on the next activation, after which which of the two a partner is
        # priced with comes down to `sequence, id`.
        self._realign_default_pricelist_currency()

        if not enabled_pricelists and self.env.user.has_group(
            "product.group_product_pricelist"
        ):
            # `self`, not every company in the database: only the companies just
            # written can have gained a default pricelist from this call.
            self._activate_or_create_pricelists()

        return res

    def _realign_default_pricelist_currency(self):
        """Move each company's rule-less default pricelist onto its currency.

        "Rule-less" is decided by searching `product.pricelist.item` directly,
        *not* by `("item_ids", "=", False)`. `item_ids` carries a domain that
        hides rules whose product or template is archived (see
        `product.pricelist._base_domain_item_ids`), so a pricelist whose rules
        all target archived products reads as empty -- and rewriting its
        currency would silently re-denominate every `fixed_price` on those
        rules. `product.pricelist.write` avoids the same trap for the same
        reason.
        """
        if not self:
            return
        Pricelist = self.env["product.pricelist"].sudo()
        candidates = Pricelist.with_context(active_test=False).search(
            [("company_id", "in", self.ids)],
        )
        if not candidates:
            return
        with_rules = set(
            self.env["product.pricelist.item"]
            .sudo()
            .with_context(active_test=False)
            ._read_group([("pricelist_id", "in", candidates.ids)], ["pricelist_id"])
        )
        for pricelist in candidates:
            if (pricelist,) in with_rules:
                continue
            company_currency = pricelist.company_id.currency_id
            if company_currency and pricelist.currency_id != company_currency:
                pricelist.currency_id = company_currency

    def _activate_or_create_pricelists(self):
        """Manage the default pricelists for needed companies."""
        if self.env.context.get("disable_company_pricelist_creation"):
            return

        if self.env.user.has_group("product.group_product_pricelist"):
            companies = self or self.env["res.company"].search([])
            ProductPricelist = self.env["product.pricelist"].sudo()
            # Activate existing default pricelists
            default_pricelists_sudo = (
                ProductPricelist.with_context(active_test=False)
                .search([("item_ids", "=", False), ("company_id", "in", companies.ids)])
                .filtered(lambda pl: pl.currency_id == pl.company_id.currency_id)
            )
            default_pricelists_sudo.action_unarchive()
            companies_without_pricelist = companies.filtered(
                lambda c: c.id not in default_pricelists_sudo.company_id.ids
            )
            # Create missing default pricelists
            ProductPricelist.create(
                [
                    company._get_default_pricelist_vals()
                    for company in companies_without_pricelist
                ]
            )

    def _get_default_pricelist_vals(self):
        """Add values to the default pricelist at company creation or activation of the pricelist

        Note: self.ensure_one()

        :rtype: dict
        """
        self.ensure_one()
        return {
            "name": _("Default"),
            "currency_id": self.currency_id.id,
            "company_id": self.id,
            "sequence": 10,
        }
