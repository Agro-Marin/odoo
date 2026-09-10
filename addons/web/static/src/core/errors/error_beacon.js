// @ts-check
/** @odoo-module native */

/**
 * @typedef {"error" | "unhandledrejection" | "module_rebind" | "service_start"
 * | "asset_load_error"} JsErrorKind
 */

/**
 * @typedef {{
 * message: unknown,
 * kind?: JsErrorKind,
 * phase?: string,
 * filename?: string,
 * line?: number,
 * col?: number,
 * stack?: string,
 * cause?: unknown,
 * reloaded?: boolean,
 * dedup?: boolean,
 * }} JsErrorInfo
 */

/**
 * @param {JsErrorInfo} info
 * @returns {boolean}
 */
export function reportJsError(info) {
    const beacon = /** @type {any} */ (globalThis).odoo?.loader?._beacon;
    return beacon ? beacon.reportJsError(info) : false;
}
