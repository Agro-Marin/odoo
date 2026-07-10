// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/asset_log - Debug-gated namespaced logger (asset/rpc/action/model) */

/**
 * Build a namespaced ``console.debug`` logger with its own activation toggle,
 * so any subsystem (RPC, action, model, ...) can add tracing without inventing
 * its own opt-in. A namespace activates via ``?debug=<flagSubstring>``,
 * ``localStorage.setItem("debug.<flagSubstring>", "1")``, or a truthy
 * ``globalThis[extraGlobalFlag]``. The returned ``log(category, ...parts)``
 * exposes ``.enabled()`` for callers that want to skip expensive payload
 * construction before logging.
 *
 * @param {string} prefix          Log-line prefix, e.g. ``"asset"`` → ``[asset.boot] ...``.
 * @param {string} flagSubstring   Token matched in ``odoo.debug`` and used as
 *                                 the ``debug.<flagSubstring>`` localStorage key.
 *                                 The asset namespace uses ``"asset"`` for the
 *                                 prefix but ``"assets"`` for the flag (back-compat).
 * @param {string} [extraGlobalFlag] Optional ``globalThis`` property name that
 *                                 also activates the namespace when truthy.
 * @returns {((category: string, ...parts: any[]) => void) & { enabled: () => boolean }}
 */
function _makeNamespacedLog(prefix, flagSubstring, extraGlobalFlag) {
    const flagKey = `debug.${flagSubstring}`;
    const enabled = () => {
        // Not cached: debug flag can flip at runtime (menu toggle, DevTools
        // edit). Check is O(1) string ops, run only when something logs.
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
        } catch {
            // localStorage may throw in sandboxed iframes — treat as disabled.
        }
        return false;
    };
    /** @type {any} */
    const log = (/** @type {string} */ category, /** @type {any[]} */ ...parts) => {
        if (!enabled()) {
            return;
        }
        // Use console.debug so devtools hides this behind "Verbose".
        // The prefix makes logs greppable; console does its own formatting.
        console.debug(`[${prefix}.${category}]`, ...parts);
    };
    log.enabled = enabled;
    return log;
}

// Public namespace logs

/** Asset / bundle / ESM tracing — the historical surface. Flag: ``assets``, also ``window.__ODOO_ASSET_TRACE__``. */
export const assetLog = _makeNamespacedLog("asset", "assets", "__ODOO_ASSET_TRACE__");

/** RPC lifecycle tracing — request / response / error / abort / timeout. Flag: ``rpc``. */
export const rpcLog = _makeNamespacedLog("rpc", "rpc");

/** Action manager tracing — doAction dispatch, executor routing, breadcrumb stack mutations. Flag: ``action``. */
export const actionLog = _makeNamespacedLog("action", "action");

/** Relational-model tracing — root load, save, discard, onchange. Flag: ``model``. */
export const modelLog = _makeNamespacedLog("model", "model");

/** Localization tracing — translation fetch, cache hits, application. Flag: ``l10n``. */
export const l10nLog = _makeNamespacedLog("l10n", "l10n");

// Scoped logger factories (partial application by category)

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
