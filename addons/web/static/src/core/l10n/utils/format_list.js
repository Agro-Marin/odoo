// @ts-check
/** @odoo-module native */

import { localization } from "@web/core/l10n/localization";
import { pyToJsLocale } from "@web/core/l10n/utils/locales";

/**
 * @typedef {keyof typeof LIST_STYLES} FormatListStyle
 */

const LIST_STYLES = /** @type {const} */ ({
    standard: {
        type: "conjunction",
        style: "long",
    },
    "standard-short": {
        type: "conjunction",
        style: "short",
    },
    or: {
        type: "disjunction",
        style: "long",
    },
    "or-short": {
        type: "disjunction",
        style: "short",
    },
    unit: {
        type: "unit",
        style: "long",
    },
    "unit-short": {
        type: "unit",
        style: "short",
    },
    "unit-narrow": {
        type: "unit",
        style: "narrow",
    },
});

/** @type {Map<string, Intl.ListFormat>} */
const _listFormatCache = new Map();

/**
 * @param {Iterable<string>} values
 * @param {{
 * localeCode?: string;
 * style?: FormatListStyle;
 * }} [options]
 * @returns {string}
 */
export function formatList(values, { localeCode, style } = {}) {
    const locale = localeCode || pyToJsLocale(localization.code) || "en-US";
    const listStyle = style || "standard";
    const cacheKey = `${locale}|${listStyle}`;
    let formatter = _listFormatCache.get(cacheKey);
    if (!formatter) {
        formatter = new Intl.ListFormat(locale, LIST_STYLES[listStyle]);
        _listFormatCache.set(cacheKey, formatter);
    }
    return formatter.format(Array.from(values, String));
}
