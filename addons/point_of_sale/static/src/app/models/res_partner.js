/** @odoo-module native */
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
export class ResPartner extends Base {
    static pythonModel = "res.partner";

    get phone() {
        return this.phone_ids?.[0]?.number || "";
    }

    get phoneNumbers() {
        return (this.phone_ids || []).map((phone) => phone.number).join(", ");
    }

    get searchString() {
        const fields = [
            "name",
            "barcode",
            "phone",
            "email",
            "vat",
            "parent_name",
            "pos_contact_address",
        ];
        return fields
            .map((field) => {
                if (field === "phone" && this[field]) {
                    return this[field].replace(/[+\s()-]/g, "");
                }
                return this[field] || "";
            })
            .filter(Boolean)
            .join(" ");
    }

    exactMatch(searchWord) {
        const fields = ["barcode"];
        return fields.some(
            (field) => this[field] && this[field].toLowerCase() === searchWord,
        );
    }
}
registry.category("pos_available_models").add(ResPartner.pythonModel, ResPartner);
