// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/monetary/monetary_field - Currency-aware numeric input field for Monetary columns */

import { useEffect } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { nbsp } from "@web/core/utils/format/strings";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import { isFalseEmpty } from "@web/fields/field_utils";
import { formatMonetary } from "@web/fields/formatters";
import { parseMonetary } from "@web/fields/parsers";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getCurrency } from "@web/services/currency";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class MonetaryField extends NumericInputFieldBase {
    static template = "web.MonetaryField";
    static props = {
        ...standardFieldProps,
        currencyField: { type: String, optional: true },
        inputType: { type: String, optional: true },
        useFieldDigits: { type: Boolean, optional: true },
        hideSymbol: { type: Boolean, optional: true },
        trailingZeros: { type: Boolean, optional: true },
    };
    static defaultProps = {
        hideSymbol: false,
        inputType: "text",
        trailingZeros: true,
    };

    /** @type {{ hasFocus: boolean, value?: string }} */
    state;

    setup() {
        useRenderCounter("fields.MonetaryField");
        super.setup();
        // Mirrors the input's current text so the template's ghost <span> can
        // size the currency symbol placement (kept in sync via onInput below).
        this.state.value = /** @type {string | undefined} */ (undefined);
        this.nbsp = nbsp;
        useEffect(() => {
            if (this.inputRef?.el) {
                this.state.value = this.inputRef.el.value;
            }
        });
    }

    /** @param {string} v @returns {number} */
    parse(v) {
        return this.parseNumericInput(v, (val) =>
            parseMonetary(val, { allowOperation: true }),
        );
    }

    /** @returns {number | undefined} */
    get currencyId() {
        const currencyField =
            this.props.currencyField ||
            this.props.record.fields[this.props.name].currency_field ||
            "currency_id";
        const currency = this.props.record.data[currencyField];
        return currency?.id;
    }
    /** @returns {NonNullable<ReturnType<typeof getCurrency>> | null} */
    get currency() {
        const id = this.currencyId;
        if (id !== undefined && !isNaN(id)) {
            return getCurrency(id) || null;
        }
        return null;
    }

    /** @returns {string} */
    get currencySymbol() {
        return this.currency ? this.currency.symbol : "";
    }

    /** @returns {[number, number] | null} */
    get currencyDigits() {
        if (this.props.useFieldDigits) {
            return this.props.record.fields[this.props.name].digits;
        }
        const currency = this.currency;
        if (!currency) {
            return null;
        }
        return currency.digits;
    }

    /** @returns {string|number} */
    get formattedValue() {
        if (this.props.inputType === "number" && !this.props.readonly) {
            // A `<input type="number">` can't hold a locale-formatted string (e.g.
            // "0,00" blanks the field in comma-decimal locales), so emit the raw
            // number: `false` (unset) becomes "", `0` is preserved (same fix as
            // FloatField.formattedValue).
            return this.value === false ? "" : this.value;
        }
        return formatMonetary(this.value, {
            digits: this.currencyDigits,
            minDigits:
                this.props.useFieldDigits &&
                this.props.record.fields[this.props.name].min_display_digits,
            currencyId: this.currencyId,
            noSymbol: !this.props.readonly || this.props.hideSymbol,
            trailingZeros: this.props.trailingZeros,
        });
    }

    /** @param {InputEvent & { target: HTMLInputElement }} ev */
    onInput(ev) {
        this.state.value = ev.target.value;
    }
}

export const monetaryField = {
    component: MonetaryField,
    supportedOptions: [
        {
            label: _t("Hide symbol"),
            name: "no_symbol",
            type: "boolean",
        },
        {
            label: _t("Currency"),
            name: "currency_field",
            type: "field",
            availableTypes: ["many2one"],
        },
        {
            label: _t("Hide trailing zeros"),
            name: "hide_trailing_zeros",
            type: "boolean",
            help: _t(
                "Hide zeros to the right of the last non-zero digit, e.g. 1.20 becomes 1.2",
            ),
        },
    ],
    supportedTypes: ["monetary", "float", "integer"],
    displayName: _t("Monetary"),
    isEmpty: isFalseEmpty,
    extractProps: ({ attrs, options }) => ({
        currencyField: options.currency_field,
        inputType: attrs.type,
        useFieldDigits: options.field_digits,
        hideSymbol: options.no_symbol,
        trailingZeros: !options.hide_trailing_zeros,
    }),
};

registerField("monetary", monetaryField);
