/** @odoo-module native */
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
export class AccountFiscalPosition extends Base {
    static pythonModel = "account.fiscal.position";

    getTaxesAfterFiscalPosition(taxes) {
        if (!this.tax_ids?.length) {
            // Mirror Python's account.fiscal.position.map_tax: a position with no
            // tax mapping keeps only the taxes that are not themselves scoped to a
            // fiscal position (the tax-units pattern), dropping the scoped ones.
            // This is a per-tax filter, not an all-or-nothing decision.
            return taxes.filter((tax) => !tax.fiscal_position_ids?.length);
        }

        const taxMap = this.tax_map || {};
        const newTaxIds = [];
        for (const tax of taxes) {
            if (taxMap[tax.id]) {
                for (const mapTaxId of taxMap[tax.id]) {
                    newTaxIds.push(mapTaxId);
                }
            } else {
                newTaxIds.push(tax.id);
            }
        }

        return this.models["account.tax"].filter((tax) => newTaxIds.includes(tax.id));
    }
}

registry
    .category("pos_available_models")
    .add(AccountFiscalPosition.pythonModel, AccountFiscalPosition);
