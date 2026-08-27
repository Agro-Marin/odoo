// @ts-check
/** @odoo-module native */
/* eslint-disable no-console -- dedicated asset logging utility; console is its output */

const _globals = /** @type {Record<string, any>} */ (globalThis);

/**
 * @param {string} key
 */
function _record(key) {
    if (!_globals.__odooTrace) {
        return;
    }
    const counts = (_globals.__odooTraceCounts_ ||= Object.create(null));
    counts[key] = (counts[key] || 0) + 1;
}

/**
 * @param {string} prefix
 * @param {string} flagSubstring
 * @param {string} [extraGlobalFlag]
 * @returns {((category: string, ...parts: any[]) => void) & {
 * enabled: () => boolean,
 * active: () => boolean,
 * }}
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
        _record(`${prefix}.${category}`);
        if (!enabled()) {
            return;
        }
        console.debug(`[${prefix}.${category}]`, ...parts);
    };
    log.enabled = enabled;
    log.active = () => enabled() || Boolean(_globals.__odooTrace);
    return log;
}

export const assetLog = _makeNamespacedLog("asset", "assets", "__ODOO_ASSET_TRACE__");

export const rpcLog = _makeNamespacedLog("rpc", "rpc");

export const actionLog = _makeNamespacedLog("action", "action");

export const modelLog = _makeNamespacedLog("model", "model");

export const l10nLog = _makeNamespacedLog("l10n", "l10n");

export const componentLog = _makeNamespacedLog("component", "component");

export const serviceLog = _makeNamespacedLog("service", "service");

export const viewLog = _makeNamespacedLog("view", "view");

export const fieldLog = _makeNamespacedLog("field", "field");

export const livechatLog = _makeNamespacedLog("livechat", "livechat");

/**
 * @param {ReturnType<typeof _makeNamespacedLog>} namespaced
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
function _bindCategory(namespaced, category) {
    /** @type {any} */
    const log = (/** @type {any[]} */ ...parts) => namespaced(category, ...parts);
    log.enabled = namespaced.enabled;
    log.active = namespaced.active;
    return log;
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeAssetLog(category) {
    return _bindCategory(assetLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeRpcLog(category) {
    return _bindCategory(rpcLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeActionLog(category) {
    return _bindCategory(actionLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeModelLog(category) {
    return _bindCategory(modelLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeL10nLog(category) {
    return _bindCategory(l10nLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeComponentLog(category) {
    return _bindCategory(componentLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeServiceLog(category) {
    return _bindCategory(serviceLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeViewLog(category) {
    return _bindCategory(viewLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeFieldLog(category) {
    return _bindCategory(fieldLog, category);
}

/**
 * @param {string} category
 * @returns {((...parts: any[]) => void) & { enabled: () => boolean, active: () => boolean }}
 */
export function makeLivechatLog(category) {
    return _bindCategory(livechatLog, category);
}

/**
 * @returns {boolean}
 */
function _traceArmedAtInit() {
    try {
        if (globalThis.location?.search?.includes("odoo-trace")) {
            return true;
        }
        if (globalThis.localStorage?.getItem?.("debug.trace")) {
            return true;
        }
    } catch {}
    return false;
}

if (typeof _globals.__odooTraceStats !== "function") {
    _globals.__odooTraceStats = () =>
        Object.assign(Object.create(null), _globals.__odooTraceCounts_ || {});
    _globals.__odooTraceReset = () => {
        _globals.__odooTraceCounts_ = Object.create(null);
    };
    _globals.__odooTrace = _traceArmedAtInit();
}
