// @ts-check
/** @odoo-module native */
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
export class ResCompany extends Base {
    static pythonModel = "res.company";

    get phone() {
        return this.phone_ids?.[0]?.number || "";
    }
}
registry.category("pos_available_models").add(ResCompany.pythonModel, ResCompany);
