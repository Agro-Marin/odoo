// @ts-check
/** @odoo-module native */

import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/translation";

/**
 * @param {string} value
 * @returns {boolean}
 */
export function isBinarySize(value) {
    return /^\d+(\.\d*)? [^0-9]+$/.test(value);
}

/**
 * @param {number} maxBytes
 * @returns {number}
 */
export function toBase64Length(maxBytes) {
    return Math.ceil((maxBytes * 4) / 3);
}

/**
 * @param {number} size
 * @returns {string}
 */
export function humanSize(size) {
    const units = _t("Bytes|KB|MB|GB|TB|PB|EB|ZB|YB").split("|");
    let i = 0;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        ++i;
    }
    const formatted = size.toFixed(2).replace(".", localization.decimalPoint);
    return `${formatted} ${units[i].trim()}`;
}
