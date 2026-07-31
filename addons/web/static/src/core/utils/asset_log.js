// @ts-check
/** @odoo-module native */
/* eslint-disable no-console -- dedicated asset logging utility; console is its output */

/** @module @web/core/utils/asset_log */

/**
 * @param {string} prefix
 * @param {string} flagSubstring
 * @param {string} [extraGlobalFlag]
 * @returns {((category: string, ...parts: any[]) => void) & { enabled: () => boolean }}
 */
function _makeNamespacedLog(prefix, flagSubstring, extraGlobalFlag) {
    const flagKey = `debug.${flagSubstring}`;
    const enabled = () => {
        try {
            const o = /** @type {any} */ (globalThis).odoo;
            if (o && typeof o.debug === "string" && o.debug.includes(flagSubstring)) {
                return true;
            }
            if (globalThis.localStorage?.getItem?.(flagKey)) {
                return true;
            }
            if (extraGlobalFlag && /** @type {any} */ (globalThis)[extraGlobalFlag]) {
                return true;
            }
        } catch {}
        return false;
    };
    /** @type {any} */
    const log = (/** @type {string} */ category, /** @type {any[]} */ ...parts) => {
        if (!enabled()) {
            return;
        }
        console.debug(`[${prefix}.${category}]`, ...parts);
    };
    log.enabled = enabled;
    return log;
}

export const assetLog = _makeNamespacedLog("asset", "assets", "__ODOO_ASSET_TRACE__");

export const rpcLog = _makeNamespacedLog("rpc", "rpc");

export const actionLog = _makeNamespacedLog("action", "action");

export const modelLog = _makeNamespacedLog("model", "model");

export const l10nLog = _makeNamespacedLog("l10n", "l10n");

/**
 * @param {string} category
 * @returns {(...parts: any[]) => void}
 */
export function makeAssetLog(category) {
    return (...parts) => assetLog(category, ...parts);
}

/**
 * @param {string} category
 * @returns {(...parts: any[]) => void}
 */
export function makeRpcLog(category) {
    return (...parts) => rpcLog(category, ...parts);
}

/**
 * @param {string} category
 * @returns {(...parts: any[]) => void}
 */
export function makeActionLog(category) {
    return (...parts) => actionLog(category, ...parts);
}

/**
 * @param {string} category
 * @returns {(...parts: any[]) => void}
 */
export function makeModelLog(category) {
    return (...parts) => modelLog(category, ...parts);
}
