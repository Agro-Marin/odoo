// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/format/binary - Binary size detection, base64 length calculation, and human-readable byte formatting */

import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";

/**
 * @param {string} value
 * @returns {boolean}
 */
export function isBinarySize(value) {
    return /^\d+(\.\d*)? [^0-9]+$/.test(value);
}

/**
 * Get the length necessary for a base64 str to encode maxBytes
 * @param {number} maxBytes number of bytes we want to encode in base64
 * @returns {number} number of char
 */
export function toBase64Length(maxBytes) {
    return Math.ceil((maxBytes * 4) / 3);
}

/**
 * @param {number} size number of bytes
 * @returns {string}
 */
export function humanSize(size) {
    // These are BYTE units, so the binary-multiple abbreviations are "KB",
    // "MB", ... (uppercase B = bytes); "Kb"/"Mb" mean *bits* and were wrong.
    const units = _t("Bytes|KB|MB|GB|TB|PB|EB|ZB|YB").split("|");
    let i = 0;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        ++i;
    }
    // Respect the user's locale decimal separator (e.g. "2,52 MB" in fr_FR)
    // instead of always emitting a "." like Number.toFixed does.
    const formatted = size.toFixed(2).replace(".", localization.decimalPoint);
    return `${formatted} ${units[i].trim()}`;
}
