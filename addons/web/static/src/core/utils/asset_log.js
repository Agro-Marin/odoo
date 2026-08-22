// @ts-check
/** @odoo-module native */
/* eslint-disable no-console -- dedicated asset logging utility; console is its output */

const _globals = /** @type {Record<string, any>} */ (globalThis);

/**
 * Records one occurrence of `key` in the structured trace sink.
 *
 * Deliberately independent of the console gate below. `__odooTrace` counts with
 * no console output, which is what a measurement run behind a machine-doc figure
 * wants; `debug.<namespace>` emits the human-readable trace it always did. Either
 * can be on without the other, and when `__odooTrace` is off this costs one
 * property read.
 *
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
 *   enabled: () => boolean,
 *   active: () => boolean,
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
    /**
     * Whether ANYTHING is listening -- console gate or structured sink.
     *
     * A call site that skips work when logging is off must ask this rather than
     * `enabled()`. `enabled()` alone answers only "is the console listening",
     * so guarding on it makes the namespace invisible to `__odooTrace` no
     * matter how the sink is armed. That is not hypothetical: both RPC
     * listeners in `core/network/rpc.js` guarded on `enabled()`, and `rpc.*`
     * recorded nothing on a fully instrumented page boot until they moved here.
     */
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

export const mailLog = _makeNamespacedLog("mail", "mail");

/**
 * The livechat embed is the hardest runtime in the tree to observe: it removes
 * the `error` service on purpose (`embed/cors/boot.js`), it runs on a page Odoo
 * does not render, and under CORS it rewrites every request's origin. Give it a
 * namespace of its own rather than borrowing `rpc`'s.
 */
export const livechatLog = _makeNamespacedLog("livechat", "livechat");

/**
 * Bind a namespace to one category, keeping the `enabled`/`active` predicates.
 *
 * Without this the `make*Log` wrappers returned a bare arrow, so a call site
 * that took one could not ask whether anything was listening -- and the module
 * requires exactly that of any call site that builds a payload before logging
 * (see `active` on `_makeNamespacedLog`). `store_service`'s per-batch
 * `fetchParams.map(...)` is one: it would allocate on every store fetch with
 * the namespace off.
 *
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
 * Whether the structured sink is armed at module-evaluation time.
 *
 * This has to be decided HERE rather than by a later assignment, because the
 * two boot-time probes -- `service.start` and `component.mount` -- have already
 * fired by the time any page script could set the flag. Arming after boot
 * observes an empty boot and reports it as one, which is worse than not
 * measuring at all.
 *
 * The URL is read DIRECTLY rather than through `odoo.debug`, because the server
 * normalises the debug parameter against an allowlist -- `ALLOWED_DEBUG_MODES =
 * ["", "1", "assets", "tests"]` in `web/models/ir_http.py`. Anything else, this
 * campaign's namespaces included, is rewritten to "1" before the page is built,
 * so `?debug=rpc` has never reached `rpcLog`. `location.search` is not
 * normalised by anyone, and needs no change to a production allowlist for a
 * surface that gets deleted at the end of the campaign.
 *
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
