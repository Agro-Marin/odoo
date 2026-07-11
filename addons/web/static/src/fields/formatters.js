// @ts-check
/** @odoo-module native */

/** @module @web/fields/formatters - Field value formatters for all ORM field types (date, float, monetary, selection, etc.) */

import { markup } from "@odoo/owl";
import {
    formatDate as _formatDate,
    formatDateTime as _formatDateTime,
    toLocaleDateString,
    toLocaleDateTimeString,
} from "@web/core/l10n/dates";
import { localization as l10n } from "@web/core/l10n/localization";
import { _pl, _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { isBinarySize } from "@web/core/utils/format/binary";
import {
    formatFloat as formatFloatNumber,
    humanNumber,
    insertThousandsSep,
} from "@web/core/utils/format/numbers";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { extractDigits } from "@web/fields/field_utils";
import { formatCurrency } from "@web/services/currency";

// Helpers

/**
 * @param {number} value
 * @returns {string}
 */
function humanSize(value) {
    if (!value) {
        return "";
    }
    const suffix = value < 1024 ? " " + _t("Bytes") : "b";
    return (
        humanNumber(value, {
            decimals: 2,
        }) + suffix
    );
}

// Exports

/**
 * @param {string} [value] base64 representation of the binary
 * @returns {string}
 */
export function formatBinary(value) {
    if (!value) {
        return "";
    }
    if (!isBinarySize(value)) {
        // Computing approximate size out of base64 encoded string
        // http://en.wikipedia.org/wiki/Base64#MIME
        return humanSize(value.length / 1.37);
    }
    // already bin_size
    return value;
}

/**
 * Read-only rendering of a boolean value as a disabled checkbox. The two
 * possible markup fragments are built once and reused (avoids a per-call
 * allocation); no id/for pairing is needed since the input is disabled and
 * the label is empty.
 *
 * @param {boolean} value
 * @returns {any}
 */
const _booleanMarkup = {
    checked: markup`<div class="o-checkbox d-inline-block me-2"><input type="checkbox" class="form-check-input" disabled checked/><label class="form-check-label"/></div>`,
    unchecked: markup`<div class="o-checkbox d-inline-block me-2"><input type="checkbox" class="form-check-input" disabled/><label class="form-check-label"/></div>`,
};
export function formatBoolean(value) {
    return value ? _booleanMarkup.checked : _booleanMarkup.unchecked;
}

/**
 * @param {string} value
 * @param {Object} [options] additional options
 * @param {boolean} [options.isPassword=false] if true, returns '********'
 *   instead of the formatted value
 * @returns {string}
 */
export function formatChar(value, options) {
    if (options?.isPassword) {
        return "*".repeat(value ? value.length : 0);
    }
    return value || "";
}
formatChar.extractOptions = ({ attrs }) => ({
    isPassword: exprToBoolean(attrs.password),
});

/**
 * @param {any} value
 * @param {Object} [options]
 * @returns {string}
 */
export function formatDate(value, options = {}) {
    if (options.numeric) {
        return _formatDate(value, options);
    } else {
        return toLocaleDateString(value);
    }
}
formatDate.extractOptions = (/** @type {any} */ { options }) => ({
    numeric: exprToBoolean(options.numeric ?? false),
});

/**
 * @param {any} value
 * @param {Object} [options]
 * @returns {string}
 */
export function formatDateTime(value, options = {}) {
    if (options.numeric) {
        if (options.showTime === false) {
            return _formatDate(value, options);
        }
        return _formatDateTime(value, options);
    } else {
        return toLocaleDateTimeString(value, options);
    }
}
formatDateTime.extractOptions = (/** @type {any} */ { attrs, options }) => ({
    ...formatDate.extractOptions({ attrs, options }),
    showSeconds: exprToBoolean(options.show_seconds ?? false),
    showTime: exprToBoolean(options.show_time ?? true),
    showDate: exprToBoolean(options.show_date ?? true),
});

/**
 * Returns a string representing a float.  The result takes into account the
 * user settings (to display the correct decimal separator).
 *
 * @param {number | false} value the value that should be formatted
 * @param {any} [options]
 * @returns {string}
 */
export function formatFloat(value, options = {}) {
    if (value === false) {
        return "";
    }
    if (!options.digits && options.field) {
        options.digits = options.field.digits;
    }
    if (!options.minDigits && options.field) {
        options.minDigits = options.field.min_display_digits;
    }
    return formatFloatNumber(value, options);
}
formatFloat.extractOptions = ({ attrs, options }) => ({
    decimals: options.decimals || 0,
    digits: extractDigits({ attrs, options }),
    minDigits: options.minDigits,
    humanReadable: !!options.human_readable,
    trailingZeros: !options.hide_trailing_zeros,
});

/**
 * Returns a string representing a float value, from a float converted with a
 * factor.
 *
 * @param {number | false} value
 * @param {any} [options]
 * @returns {string}
 */
export function formatFloatFactor(value, options = {}) {
    if (value === false) {
        return "";
    }
    const factor = options.factor || 1;
    if (!options.digits && options.field) {
        options.digits = options.field.digits;
    }
    return formatFloatNumber(value * factor, options);
}
formatFloatFactor.extractOptions = ({ attrs, options }) => ({
    ...formatFloat.extractOptions({ attrs, options }),
    factor: options.factor,
});

/**
 * Returns a string representing a time value, from a float.  The idea is that
 * we sometimes want to display something like 1:45 instead of 1.75, or 0:15
 * instead of 0.25.
 *
 * @param {number | false} value
 * @param {Object} [options]
 * @param {boolean} [options.noLeadingZeroHour] if true, format like 1:30 otherwise, format like 01:30
 * @param {boolean} [options.displaySeconds] if true, format like ?1:30:00 otherwise, format like ?1:30
 * @returns {string}
 */
export function formatFloatTime(value, options = {}) {
    if (value === false) {
        return "";
    }
    const isNegative = value < 0;
    value = Math.abs(value);

    let hour = Math.floor(value);
    const milliSecLeft = Math.round(value * 3600000) - hour * 3600000;
    // Avoids float rounding issues while treating 59s as 00:00.
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
    if (options.displaySeconds) {
        sec = ":" + String(Math.floor((milliSecLeft % 60000) / 1000)).padStart(2, "0");
    }
    return `${isNegative ? "-" : ""}${hourStr}:${minStr}${sec}`;
}
formatFloatTime.extractOptions = ({ options }) => ({
    displaySeconds: options.displaySeconds,
});

/**
 * Returns a string representing an integer.  If the value is false, then we
 * return an empty string.
 *
 * @param {any} value
 * @param {any} [options]
 * @returns {string}
 */
export function formatInteger(value, options = {}) {
    if (value === false || value === null) {
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
    if (typeof value !== "number" || !Number.isFinite(value)) {
        return "";
    }
    return insertThousandsSep(value.toFixed(0), thousandsSep, grouping);
}
formatInteger.extractOptions = ({ attrs, options }) => ({
    decimals: options.decimals || 0,
    humanReadable: !!options.human_readable,
    isPassword: exprToBoolean(attrs.password),
});

/**
 * Returns a string representing a many2one value. The value is expected to be
 * either `false` or an array in the form [id, display_name] or an object
 * containing at least the key "display_name". The returned value will then be
 * the display name of the given value, or an empty string if the value is false.
 *
 * @param {any} value
 * @param {Object} [options] additional options
 * @param {boolean} [options.escape=false] if true, URL-encodes the formatted
 *   value via `encodeURIComponent` (this is percent-encoding for use in a URL,
 *   NOT HTML escaping). Shared generic formatter option (see list aggregates).
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
 * Returns a string representing a one2many or many2many value. The value is
 * expected to be either `false` or an array of ids. The returned value will
 * then be the count of ids in the given value in the form "x record(s)".
 *
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
 * Returns a string representing a monetary value. The result takes into account
 * the user settings (to display the correct decimal separator, currency, ...).
 *
 * @param {number | false} value the value that should be formatted
 * @param {any} [options]
 * @returns {string}
 */
export function formatMonetary(value, options = {}) {
    // Display nothing when unset; a value of 0 would be misleading here.
    if (value === false) {
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
formatMonetary.extractOptions = ({ options }) => ({
    noSymbol: options.no_symbol,
    currencyField: options.currency_field,
    trailingZeros: !options.hide_trailing_zeros,
});

/**
 * Returns a string representing the given value (multiplied by 100)
 * concatenated with '%'.
 *
 * @param {number | false} value
 * @param {any} [options]
 * @returns {string}
 */
export function formatPercentage(value, options = {}) {
    if (
        value === false ||
        /** @type {any} */ (value) == null ||
        /** @type {any} */ (value) === ""
    ) {
        // `false` (unset) renders empty like formatFloat, not as "0%".
        return "";
    }
    options = Object.assign({ trailingZeros: false, thousandsSep: "" }, options);
    if (!options.digits && options.field) {
        options.digits = options.field.digits;
    }
    const formatted = formatFloatNumber(/** @type {any} */ (value) * 100, options);
    return `${formatted}${options.noSymbol ? "" : "%"}`;
}
formatPercentage.extractOptions = formatFloat.extractOptions;

/**
 * Returns a string representing the value of the python properties field
 * or a properties definition field (see fields.py@Properties).
 *
 * @param {any[]|false} value
 */
function formatProperties(value) {
    if (!value || !value.length) {
        return "";
    }
    return value.map((property) => property["string"]).join(", ");
}

/**
 * Returns a string representing the value of the reference field.
 *
 * @param {Object|false} value Object with keys "resId" and "displayName"
 * @param {Object} [options={}]
 * @returns {string}
 */
export function formatReference(value, options) {
    return formatMany2one(
        value ? { id: value.resId, display_name: value.displayName } : false,
        options,
    );
}

/**
 * Returns a string representing the value of the many2one_reference field.
 *
 * @param {Object|false} value Object with keys "resId" and "displayName"
 * @returns {string}
 */
export function formatMany2oneReference(value) {
    return value
        ? formatMany2one({ id: value.resId, display_name: value.displayName })
        : "";
}

/**
 * Returns a string of the value of the selection.
 *
 * @param {Object} [options={}]
 * @param {[string, string][]} [options.selection]
 * @param {Object} [options.field]
 * @returns {string}
 */
export function formatSelection(value, options = {}) {
    const selection =
        options.selection || (options.field && options.field.selection) || [];
    const option = selection.find((option) => option[0] === value);
    return option ? option[1] : "";
}

/**
 * Returns the value or an empty string if it's falsy.
 *
 * @param {string | false} value
 * @returns {string}
 */
export function formatText(value) {
    return value ? value.toString() : "";
}

/**
 * Returns the value, kept for symmetry with the rest of the formatters.
 *
 * @param {any} value
 * @returns {any}
 */
export function formatHtml(value) {
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
    .add("date", formatDate)
    .add("datetime", formatDateTime)
    .add("float", formatFloat)
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

// Every formatter must be a callable (the optional ``.extractOptions``
// static is duck-typed by callers and not enforced here). Runs against
// existing entries and any third-party additions; in debug mode a bad
// registration throws, in production it's a ``console.warn`` so a single
// mis-shaped entry doesn't crash the page.
registry.category("formatters").addValidation((v) => typeof v === "function");
