// @ts-check
/** @odoo-module native */

/** @typedef {"error" | "unhandledrejection" | "module_rebind" | "service_start" */

/** @typedef {{ */

/**
 * @param {JsErrorInfo} info
 * @returns {boolean}
 */
export function reportJsError(info) {
    const beacon = /** @type {any} */ (globalThis).odoo?.loader?._beacon;
    return beacon ? beacon.reportJsError(info) : false;
}
