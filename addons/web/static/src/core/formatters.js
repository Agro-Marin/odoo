// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";
import {
    formatDate,
    formatDateTime,
    toLocaleDateString,
    toLocaleDateTimeString,
} from "@web/core/l10n/dates";
import { localization as l10n } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { _pl, _t } from "@web/core/translation";
import { humanSize, isBinarySize } from "@web/core/utils/format/binary";
import { extractDigits } from "@web/core/utils/format/digits";
import {
    formatFloat,
    humanNumber,
    insertThousandsSep,
} from "@web/core/utils/format/numbers";
import { exprToBoolean } from "@web/core/utils/format/strings";

/**
 * @typedef {{ attrs: Record<string, any>, options: Record<string, any> }} FieldInfoNode
 */

/**
 * @param {unknown} value
 * @returns {value is number}
 */
function isFiniteNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
}

/**
 * @param {string} [value]
 * @returns {string}
 */
export function formatBinary(value) {
    if (!value) {
        return "";
    }
    if (!isBinarySize(value)) {
        return humanSize(value.length / 1.37);
    }
    return value;
}

const _booleanMarkup = {
    checked: markup`<div class="o-checkbox d-inline-block me-2"><input type="checkbox" class="form-check-input" disabled checked/><label class="form-check-label"/></div>`,
    unchecked: markup`<div class="o-checkbox d-inline-block me-2"><input type="checkbox" class="form-check-input" disabled/><label class="form-check-label"/></div>`,
};
/**
 * @param {boolean} value
 * @returns {any}
 */
function formatBoolean(value) {
    return value ? _booleanMarkup.checked : _booleanMarkup.unchecked;
}

/**
 * @param {string} value
 * @param {Object} [options]
 * @param {boolean} [options.isPassword=false]
 * @returns {string}
 */
export function formatChar(value, options) {
    if (options?.isPassword) {
        return "*".repeat(value ? value.length : 0);
    }
    return value || "";
}
/** @param {FieldInfoNode} node */
formatChar.extractOptions = ({ attrs }) => ({
    isPassword: exprToBoolean(attrs.password),
});

/**
 * @param {any} value
 * @param {{ numeric?: boolean, format?: string, tz?: string }} [options]
 * @returns {string}
 */
export function formatFieldDate(value, options = {}) {
    if (options.numeric) {
        return formatDate(value, options);
    } else {
        return toLocaleDateString(value);
    }
}
/** @param {FieldInfoNode} node */
formatFieldDate.extractOptions = ({ options }) => ({
    numeric: exprToBoolean(options.numeric ?? false),
});

/**
 * @param {any} value
 * @param {{
 * numeric?: boolean,
 * showTime?: boolean,
 * showDate?: boolean,
 * showSeconds?: boolean,
 * format?: string,
 * tz?: string,
 * }} [options]
 * @returns {string}
 */
export function formatFieldDateTime(value, options = {}) {
    if (options.numeric) {
        if (options.showTime === false) {
            return formatDate(value, options);
        }
        return formatDateTime(value, options);
    } else {
        return toLocaleDateTimeString(value, options);
    }
}
/** @param {FieldInfoNode} node */
formatFieldDateTime.extractOptions = ({ attrs, options }) => ({
    ...formatFieldDate.extractOptions({ attrs, options }),
    showSeconds: exprToBoolean(options.show_seconds ?? false),
    showTime: exprToBoolean(options.show_time ?? true),
    showDate: exprToBoolean(options.show_date ?? true),
});

/**
 * @param {number | false} value
 * @param {any} [options]
 * @returns {string}
 */
export function formatFieldFloat(value, options = {}) {
    if (!isFiniteNumber(value)) {
        return "";
    }
    const digits = options.digits || options.field?.digits;
    const minDigits = options.minDigits || options.field?.min_display_digits;
    return formatFloat(value, { ...options, digits, minDigits });
}
/** @param {FieldInfoNode} node */
formatFieldFloat.extractOptions = ({ attrs, options }) => ({
    decimals: options.decimals || 0,
    digits: extractDigits({ attrs, options }),
    minDigits: options.min_display_digits,
    humanReadable: !!options.human_readable,
    trailingZeros: !options.hide_trailing_zeros,
});

/**
 * @param {number | false} value
 * @param {any} [options]
 * @returns {string}
 */
export function formatFloatFactor(value, options = {}) {
    if (!isFiniteNumber(value)) {
        return "";
    }
    const factor = options.factor || 1;
    const digits = options.digits || options.field?.digits;
    return formatFloat(value * factor, { ...options, digits });
}
/** @param {FieldInfoNode} node */
formatFloatFactor.extractOptions = ({ attrs, options }) => ({
    ...formatFieldFloat.extractOptions({ attrs, options }),
    factor: options.factor,
});

/**
 * @param {number | false} value
 * @param {Object} [options]
 * @param {boolean} [options.noLeadingZeroHour]
 * @param {boolean} [options.displaySeconds]
 * @returns {string}
 */
export function formatFloatTime(value, options = {}) {
    if (!isFiniteNumber(value)) {
        return "";
    }
    const isNegative = value < 0;
    value = Math.abs(value);

    let hour = Math.floor(value);
    const milliSecLeft = Math.round(value * 3600000) - hour * 3600000;
    let min = milliSecLeft / 60000;
    if (options.displaySeconds) {
        min = Math.floor(min);
    } else {
        min = Math.round(min);
    }
    if (min === 60) {
        min = 0;
        hour = hour + 1;
    }
    const minStr = String(min).padStart(2, "0");
    let hourStr = String(hour);
    if (!options.noLeadingZeroHour) {
        hourStr = hourStr.padStart(2, "0");
    }
    let sec = "";
    let secValue = 0;
    if (options.displaySeconds) {
        secValue = Math.floor((milliSecLeft % 60000) / 1000);
        sec = ":" + String(secValue).padStart(2, "0");
    }
    const showSign = isNegative && (hour !== 0 || min !== 0 || secValue !== 0);
    return `${showSign ? "-" : ""}${hourStr}:${minStr}${sec}`;
}
/** @param {FieldInfoNode} node */
formatFloatTime.extractOptions = ({ options }) => ({
    displaySeconds: options.displaySeconds,
});

/**
 * @param {any} value
 * @param {any} [options]
 * @returns {string}
 */
export function formatInteger(value, options = {}) {
    if (!isFiniteNumber(value)) {
        return "";
    }
    if (options.isPassword) {
        return "*".repeat(String(value).length);
    }
    if (options.humanReadable) {
        return humanNumber(value, options);
    }
    const grouping = options.grouping || l10n.grouping;
    const thousandsSep =
        "thousandsSep" in options ? options.thousandsSep : l10n.thousandsSep;
    let digits =
        Math.abs(value) >= 1e21
            ? BigInt(Math.trunc(value)).toString()
            : value.toFixed(0);
    if (digits === "-0") {
        digits = "0";
    }
    return insertThousandsSep(digits, thousandsSep, grouping);
}
/** @param {FieldInfoNode} node */
formatInteger.extractOptions = ({ attrs, options }) => ({
    decimals: options.decimals || 0,
    humanReadable: !!options.human_readable,
    isPassword: exprToBoolean(attrs.password),
});

/**
 * @param {any} value
 * @param {Object} [options]
 * @param {boolean} [options.escape=false]
 * @returns {string}
 */
export function formatMany2one(value, options) {
    /** @type {any} */
    let result;
    if (!value) {
        result = "";
    } else {
        const displayName = "display_name" in value ? value.display_name : value[1];
        result =
            displayName == null || displayName === false ? _t("Unnamed") : displayName;
    }
    if (options?.escape) {
        result = encodeURIComponent(result);
    }
    return result;
}

/**
 * @param {any} value
 * @returns {string}
 */
export function formatX2many(value) {
    const count = value?.currentIds?.length ?? 0;
    if (count === 0) {
        return _t("No records");
    }
    return _pl(count, {
        one: _t("1 record"),
        other: _t("%s records", count),
    });
}

/**
 * @param {number | false} value
 * @param {any} [options]
 * @returns {string}
 */
export function formatMonetary(value, options = {}) {
    if (!isFiniteNumber(value)) {
        return "";
    }

    let currencyId = options.currencyId;
    if (!currencyId && options.data) {
        const currencyField =
            options.currencyField ||
            (options.field && options.field.currency_field) ||
            "currency_id";
        const dataValue = options.data[currencyField];
        currencyId = dataValue?.id ?? dataValue;
    }
    return formatCurrency(value, currencyId, options);
}
/** @param {FieldInfoNode} node */
formatMonetary.extractOptions = ({ options }) => ({
    noSymbol: options.no_symbol,
    currencyField: options.currency_field,
    trailingZeros: !options.hide_trailing_zeros,
});

/**
 * @param {number | false} value
 * @param {any} [options]
 * @returns {string}
 */
export function formatPercentage(value, options = {}) {
    if (!isFiniteNumber(value)) {
        return "";
    }
    options = {
        trailingZeros: false,
        thousandsSep: "",
        ...options,
        digits: options.digits || options.field?.digits,
    };
    const formatted = formatFloat(/** @type {any} */ (value) * 100, options);
    return `${formatted}${options.noSymbol ? "" : "%"}`;
}
formatPercentage.extractOptions = formatFieldFloat.extractOptions;

/**
 * @param {any[]|false} value
 */
function formatProperties(value) {
    if (!value || !value.length) {
        return "";
    }
    return value.map((property) => property["string"]).join(", ");
}

/**
 * @param {{ resId: number|false, displayName: string }|false} value
 * @param {{ escape?: boolean }} [options]
 * @returns {string}
 */
export function formatReference(value, options) {
    return formatMany2one(
        value ? { id: value.resId, display_name: value.displayName } : false,
        options,
    );
}

/**
 * @param {{ resId: number|false, displayName: string }|false} value
 * @returns {string}
 */
export function formatMany2oneReference(value) {
    return value
        ? formatMany2one({ id: value.resId, display_name: value.displayName })
        : "";
}

/**
 * @param {any} value
 * @param {{ selection?: [string, string][], field?: { selection?: [string, string][] } }} [options]
 * @returns {string}
 */
export function formatSelection(value, options = {}) {
    /** @type {[string, string][]} */
    const selection =
        options.selection || (options.field && options.field.selection) || [];
    const option = selection.find((option) => option[0] === value);
    return option ? option[1] : "";
}

/**
 * @param {string | false} value
 * @returns {string}
 */
export function formatText(value) {
    return value ? value.toString() : "";
}

/**
 * @param {any} value
 * @returns {any}
 */
function formatHtml(value) {
    return value || "";
}

/**
 * @param {any} value
 * @returns {string}
 */
export function formatJson(value) {
    return (value && JSON.stringify(value)) || "";
}

registry
    .category("formatters")
    .add("binary", formatBinary)
    .add("boolean", formatBoolean)
    .add("char", formatChar)
    .add("date", formatFieldDate)
    .add("datetime", formatFieldDateTime)
    .add("float", formatFieldFloat)
    .add("float_factor", formatFloatFactor)
    .add("float_time", formatFloatTime)
    .add("html", formatHtml)
    .add("integer", formatInteger)
    .add("json", formatJson)
    .add("many2one", formatMany2one)
    .add("many2one_reference", formatMany2oneReference)
    .add("one2many", formatX2many)
    .add("many2many", formatX2many)
    .add("monetary", formatMonetary)
    .add("percentage", formatPercentage)
    .add("properties", formatProperties)
    .add("properties_definition", formatProperties)
    .add("reference", formatReference)
    .add("selection", formatSelection)
    .add("text", formatText);

registry.category("formatters").addValidation((v) => typeof v === "function");
