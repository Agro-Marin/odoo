/** @odoo-module native */
import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many";
import { useAddInlineRecord } from "@web/fields/relational/x2many_crud";

export class PaymentTermLineIdsOne2Many extends X2ManyField {
    setup() {
        super.setup();
        this.addInLine = useAddInlineRecord({
            addNew: async (...args) => {
                const newRecord = await this.list.addNewRecord(...args);
                newRecord.dirty = true;
            },
        });
    }
}

export const PaymentTermLineIds = {
    ...x2ManyField,
    component: PaymentTermLineIdsOne2Many,
};

registry.category("fields").add("payment_term_line_ids", PaymentTermLineIds);
