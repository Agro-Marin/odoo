/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { router } from "@web/core/browser/router";

export class CrmLead extends Record {
    static id = "id";
    static _name = "crm.lead";

    id;
    name;
    href = fields.Attr("", {
        compute() {
            return router.stateToUrl({ model: "crm.lead", resId: this.id });
        },
    });
}

CrmLead.register();
