/** @odoo-module native */
import { _t } from "@web/core/translation";
import { floatIsZero } from "@web/core/utils/format/numbers";
import { registerField } from "@web/fields/_registry";
import {
    MonetaryField,
    monetaryField,
} from "@web/fields/basic/monetary/monetary_field";

/**
 * Monetary field that renders a zero as blank.
 *
 * Used on the bill-matching list, where a 0 in the "Billed"/"Purchased" columns
 * means "nothing on this side" rather than "zero money", and a grid full of
 * 0.00 buries the figures that matter.
 */
export class MonetaryFieldNoZero extends MonetaryField {
    /** Override: a zero reads as absent, and `formatMonetary` blanks a non-finite value. */
    get value() {
        const originalValue = super.value;
        const decimals = this.currencyDigits ? this.currencyDigits[1] : 2;
        return floatIsZero(originalValue, decimals) ? false : originalValue;
    }
}

export const monetaryFieldNoZero = {
    ...monetaryField,
    component: MonetaryFieldNoZero,
    // Distinct from `monetary`'s: spreading left two entries in the field
    // picker both labelled "Monetary".
    displayName: _t("Monetary (hide zero)"),
    // `monetary` uses `isFalseEmpty`, which reads the *record* value and so
    // reports a stored 0.0 as non-empty while this component renders it blank.
    // Agree with what is on screen.
    isEmpty: (record, fieldName) => !record.data[fieldName],
};

registerField("monetary_no_zero", monetaryFieldNoZero);
