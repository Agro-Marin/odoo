// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/localization - Shared reactive localization object (date/number formats, direction, locale) */

/**
 * @typedef Localization
 * @property {string} dateFormat
 * @property {string} dateTimeFormat
 * @property {string} timeFormat
 * @property {string} decimalPoint
 * @property {"ltr" | "rtl"} direction
 * @property {[number, number]} grouping
 * @property {boolean} multiLang
 * @property {string} thousandsSep
 * @property {number} weekStart
 * @property {string} code
 */

/**
 * Main object holding user-specific localization data (JS counterpart of "res.lang").
 * Useful to access directly anywhere, even outside Components.
 *
 * Its data are loaded by the localization_service, so the following would not work:
 *   import { localization } from "@web/core/l10n/localization";
 *   const dateFormat = localization.dateFormat; // dateFormat isn't set yet
 * @type {Localization}
 */
// Protocol probes that must not throw before the localization data is
// loaded: "then" is read implicitly when the object is returned from an
// `async` function; the others are probed by JSON.stringify, devtools
// formatters, and assertion/inspection libraries.
const ALLOWED_PROTOCOL_KEYS = new Set(["then", "toJSON", "constructor", "inspect"]);

export const localization = new Proxy(/** @type {any} */ ({}), {
    get: (target, p) => {
        if (typeof p === "symbol" || p in target || ALLOWED_PROTOCOL_KEYS.has(p)) {
            return Reflect.get(target, p);
        }
        throw new Error(
            `could not access localization parameter "${String(p)}": parameters are not ready yet. Maybe add 'localization' to your dependencies?`,
        );
    },
});
