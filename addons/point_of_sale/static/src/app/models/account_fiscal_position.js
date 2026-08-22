/** @odoo-module native */
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
export class AccountFiscalPosition extends Base {
    static pythonModel = "account.fiscal.position";

    getTaxesAfterFiscalPosition(taxes) {
        if (!this.tax_ids?.length) {
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

        const resolved = this.models["account.tax"].readMany(newTaxIds);
        const missingIdx = resolved.findIndex((tax) => !tax);
        if (missingIdx !== -1) {
            console.warn(
                `Fiscal position '${this.name}' maps to tax id ${newTaxIds[missingIdx]} which is not loaded in this POS; the tax is ignored.`,
            );
        }
        return resolved.filter(Boolean);
    }
}

registry
    .category("pos_available_models")
    .add(AccountFiscalPosition.pythonModel, AccountFiscalPosition);
