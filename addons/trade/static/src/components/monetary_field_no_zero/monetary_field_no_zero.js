/** @odoo-module native */
import { _t } from "@web/core/translation";
import { floatIsZero } from "@web/core/utils/format/numbers";
import { registerField } from "@web/fields/_registry";
import {
    MonetaryField,
    monetaryField,
} from "@web/fields/basic/monetary/monetary_field";

export class MonetaryFieldNoZero extends MonetaryField {
    get value() {
        const originalValue = super.value;
        const decimals = this.currencyDigits ? this.currencyDigits[1] : 2;
        return floatIsZero(originalValue, decimals) ? false : originalValue;
    }
}

export const monetaryFieldNoZero = {
    ...monetaryField,
    component: MonetaryFieldNoZero,
    displayName: _t("Monetary (hide zero)"),
    isEmpty: (record, fieldName) => !record.data[fieldName],
};

registerField("monetary_no_zero", monetaryFieldNoZero);
