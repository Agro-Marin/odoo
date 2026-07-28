// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/monetary/monetary_field - Currency-aware numeric input field for Monetary columns */

import { useEffect, useRef } from "@odoo/owl";
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

    setup() {
        useRenderCounter("fields.MonetaryField");
        super.setup();
        this.nbsp = nbsp;
        this.ghostRef = useRef("ghostValue");
        // The input is uncontrolled (useInputField writes input.value
        // directly), so a model-driven change patches no DOM the renderer
        // owns. This unconditional effect re-syncs the ghost after every
        // patch; onInput covers the keystrokes in between.
        useEffect(() => this.syncGhostValue());
    }

    /**
     * Mirrors the input's text into the hidden ghost span that reserves the
     * inline space the currency symbol is positioned against.
     *
     * Written straight to the DOM rather than held in ``useState``: the ghost
     * is presentational and always equals the input's own value, so routing it
     * through reactive state made every keystroke re-render the component
     * (measured: 4 renders for 3 characters, against 0 for CharField, whose
     * input is likewise uncontrolled).
     */
    syncGhostValue() {
        if (this.ghostRef.el && this.inputRef?.el) {
            this.ghostRef.el.textContent = this.inputRef.el.value;
        }
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
            return this.rawValue;
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

    onInput() {
        this.syncGhostValue();
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
