/** @odoo-module native */
import { patch } from "@web/core/utils/patch";

import { accountTaxHelpers } from "@account/helpers/account_tax";

// -------------------------------------------------------------------------
// HELPERS IN BOTH PYTHON/JAVASCRIPT (account_tax.js / account_tax.py)
// -------------------------------------------------------------------------

patch(accountTaxHelpers, {
    // EXTENDS 'account'
    // Mirrored in Python: models/account_tax.py
    // (_round_tax_details_tax_amounts) — keep both in sync.
    round_tax_details_tax_amounts(base_lines, company, { mode = "mixed" } = {}) {
        const country_code = company.account_fiscal_country_id.code;
        if (country_code === "MX") {
            mode = "excluded";
        }
        return super.round_tax_details_tax_amounts(base_lines, company, { mode: mode });
    },

    // EXTENDS 'account'
    // Mirrored in Python: models/account_tax.py
    // (_round_tax_details_base_lines) — keep both in sync.
    round_tax_details_base_lines(base_lines, company, { mode = "mixed" } = {}) {
        const country_code = company.account_fiscal_country_id.code;
        if (country_code === "MX") {
            mode = "excluded";
        }
        return super.round_tax_details_base_lines(base_lines, company, { mode: mode });
    },
});
