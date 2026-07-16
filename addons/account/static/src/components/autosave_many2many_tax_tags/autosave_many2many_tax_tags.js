/** @odoo-module native */
import {
    Many2ManyTaxTagsField,
    many2ManyTaxTagsField,
} from "@account/components/many2x_tax_tags/many2x_tax_tags";
import { registry } from "@web/core/registry";
import { useRecordObserver } from "@web/fields/hooks/record_observer";

export class AutosaveMany2ManyTaxTagsField extends Many2ManyTaxTagsField {
    setup() {
        super.setup();

        this.lastBalance = this.props.record.data.balance;
        this.lastAccount = this.props.record.data.account_id;
        this.lastPartner = this.props.record.data.partner_id;

        useRecordObserver(this.onRecordChange.bind(this));
    }

    // The base binds `this.update` through the prototype chain (see
    // Many2ManyTagsField.setup), so overriding it as a method is the supported
    // way. Await super.update so the tag link is committed before we save.
    async update(recordlist) {
        await super.update(recordlist);
        await this._saveOnUpdate();
    }

    async deleteTag(id) {
        await super.deleteTag(id);
        await this._saveOnUpdate();
    }

    onRecordChange(record) {
        const line = record.data;
        if (line.tax_ids.records.length > 0) {
            // account_id/partner_id are `false` when unset, so guard with ?. before
            // reading .id (a fresh line can have a tax tag but no account/partner yet).
            if (
                line.balance !== this.lastBalance ||
                line.account_id?.id !== this.lastAccount?.id ||
                line.partner_id?.id !== this.lastPartner?.id
            ) {
                this.lastBalance = line.balance;
                this.lastAccount = line.account_id;
                this.lastPartner = line.partner_id;
                return record.model.root.save();
            }
        }
    }

    async _saveOnUpdate() {
        await this.props.record.model.root.save();
    }
}

export const autosaveMany2ManyTaxTagsField = {
    ...many2ManyTaxTagsField,
    component: AutosaveMany2ManyTaxTagsField,
};

registry
    .category("fields")
    .add("autosave_many2many_tax_tags", autosaveMany2ManyTaxTagsField);
