/** @odoo-module native */
import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many";
import { useAddInlineRecord } from "@web/fields/relational/x2many_crud";

export class PaymentTermLineIdsOne2Many extends X2ManyField {
    setup() {
        super.setup();
        // Mark new records as dirty so they are not abandoned when the user
        // clicks globally or on an existing record: `canBeAbandoned` is
        // `isNew && !dirty && _manuallyAdded`.
        //
        // Set the flag rather than passing an empty change set to `update()`,
        // which no longer marks anything: `_update` restores the previous dirty
        // state when the change set turns out to be empty.
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
