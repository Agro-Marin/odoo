// @ts-check
/** @odoo-module native */

import { useEffect, useRef } from "@odoo/owl";
import { getCurrency } from "@web/core/currency";
import { formatMonetary } from "@web/core/formatters";
import { parseMonetary } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { nbsp } from "@web/core/utils/format/strings";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import {
    archAttribute,
    enableFormattingOption,
    hideTrailingZerosOption,
} from "@web/fields/field_options";
import { extractFormatNumber, isFalseEmpty } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class MonetaryField extends NumericInputFieldBase {
    static template = "web.MonetaryField";
    static props = {
        ...standardFieldProps,
        currencyField: { type: String, optional: true },
        formatNumber: { type: Boolean, optional: true },
        inputType: { type: String, optional: true },
        useFieldDigits: { type: Boolean, optional: true },
        hideSymbol: { type: Boolean, optional: true },
        trailingZeros: { type: Boolean, optional: true },
    };
    static defaultProps = {
        formatNumber: true,
        hideSymbol: false,
        inputType: "text",
        trailingZeros: true,
    };

    /**
     * @type {ReturnType<typeof useRef>}
     */
    ghostRef;

    setup() {
        useRenderCounter("fields.MonetaryField");
        super.setup();
        this.nbsp = nbsp;
        this.ghostRef = useRef("ghostValue");
        useEffect(() => this.syncGhostValue());
    }

    syncGhostValue() {
        const ghostEl = this.ghostRef.el;
        const inputEl = this.inputRef?.el;
        if (ghostEl && inputEl) {
            ghostEl.textContent = inputEl.value;
        }
    }

    /**
     * @param {string} v
     * @returns {number}
     */
    parse(v) {
        return this.parseNumericInput(v, (val) =>
            parseMonetary(val, { allowOperation: true }),
        );
    }

    /** @returns {number | undefined} */
    get currencyId() {
        const currencyField =
            this.props.currencyField ||
            this.field.definition.currency_field ||
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
            return this.field.definition.digits;
        }
        const currency = this.currency;
        if (!currency) {
            return null;
        }
        return currency.digits;
    }

    /**
     * @override
     * @param {boolean} _humanReadable
     * @returns {string}
     */
    formatValue(_humanReadable) {
        return formatMonetary(this.value, {
            digits: this.currencyDigits,
            minDigits:
                this.props.useFieldDigits && this.field.definition.min_display_digits,
            currencyId: this.currencyId,
            noSymbol: !this.props.readonly || this.props.hideSymbol,
            trailingZeros: this.props.trailingZeros,
        });
    }

    onInput() {
        this.syncGhostValue();
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const monetaryField = {
    component: MonetaryField,
    supportedOptions: [
        enableFormattingOption(),
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
            label: _t("Use the field's digits"),
            name: "field_digits",
            type: "boolean",
            help: _t("Round using the field's own digits instead of the currency's."),
        },
        hideTrailingZerosOption(),
    ],
    supportedAttributes: [
        archAttribute("type", _t("Input type"), {
            help: _t(
                "Set to `number` for a native numeric input; the value is then left unformatted while editing.",
            ),
        }),
    ],
    supportedTypes: ["monetary", "float", "integer"],
    displayName: _t("Monetary"),
    isEmpty: isFalseEmpty,
    fieldDependencies: ({ options }) =>
        options.currency_field
            ? [{ name: options.currency_field, optional: true, readonly: true }]
            : [],
    extractProps: ({ attrs, options }) => ({
        currencyField: options.currency_field,
        formatNumber: extractFormatNumber(options),
        inputType: attrs.type,
        useFieldDigits: options.field_digits,
        hideSymbol: options.no_symbol,
        trailingZeros: !options.hide_trailing_zeros,
    }),
};

registerField("monetary", monetaryField);
