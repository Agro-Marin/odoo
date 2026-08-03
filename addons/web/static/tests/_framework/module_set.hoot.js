// @ts-check

import { afterEach, beforeEach, globals, mockLocation, onError } from "@odoo/hoot";

import { setupMockCurrencies } from "./mock_currency.hoot.js";
import { onServerStateChange, serverState } from "./mock_server_state.hoot.js";
import { makeSession } from "./mock_session.hoot.js";
import { setupMockTemplates } from "./mock_templates.hoot.js";

const { fetch: realFetch } = globals;

/**
 * Reduce the size of the given field and freeze it.
 *
 * @param {Record<string, unknown>} field
 */
function freezeField(field) {
    delete field.name;
    if (field.groupable) {
        delete field.groupable;
    }
    if (!field.readonly && !field.related) {
        delete field.readonly;
    }
    if (!field.required) {
        delete field.required;
    }
    if (field.searchable) {
        delete field.searchable;
    }
    if (field.sortable) {
        delete field.sortable;
    }
    if (field.store && !field.related) {
        delete field.store;
    }
    return Object.freeze(field);
}

/**
 * Reduce the size of the given model and freeze it.
 *
 * @param {Record<string, unknown>} model
 */
function freezeModel(model) {
    if (model.fields) {
        for (const [fieldName, field] of Object.entries(model.fields)) {
            model.fields[fieldName] = freezeField(field);
        }
        Object.freeze(model.fields);
    }
    if (model.inherit) {
        const inherit = /** @type {any[]} */ (model.inherit);
        if (inherit.length) {
            model.inherit = inherit.filter((m) => m !== "base");
        }
        if (!(/** @type {any[]} */ (model.inherit).length)) {
            delete model.inherit;
        }
    }
    if (model.order === "id") {
        delete model.order;
    }
    if (model.parent_name === "parent_id") {
        delete model.parent_name;
    }
    if (model.rec_name === "name") {
        delete model.rec_name;
    }
    return Object.freeze(model);
}

/**
 * @param {Record<string, unknown>} model
 */
function unfreezeModel(model) {
    const fields = Object.create(null);
    if (model.fields) {
        for (const [fieldName, field] of Object.entries(model.fields)) {
            fields[fieldName] = { ...field };
        }
    }
    return { ...model, fields };
}

const CSRF_TOKEN = odoo.csrf_token;

/** @type {Record<string, Promise<Response>>} */
const globalFetchCache = Object.create(null);
/** @type {Set<string>} */
const modelsToFetch = new Set();
/** @type {Map<string, Record<string, unknown>>} */
const serverModelCache = new Map();

let nextRpcId = 1e9;

/**
 * Prepare the test environment by patching registries and removing
 * app-specific services that crash without session state.
 *
 * Must be called BEFORE test modules are imported so that describe/test
 * calls don't encounter stale registry entries.
 */
export function setupTestEnvironment() {
    onError((ev) => {
        const error = /** @type {any} */ (ev)?.reason ?? /** @type {any} */ (ev)?.error;
        if (error?.name === "SupersededError") {
            /** @type {any} */ (ev).preventDefault?.();
        }
    });

    const { loader } = odoo;
    const registryModule = loader.modules.get("@web/core/registry");
    if (!registryModule?.Registry) {
        return;
    }

    /**
     * Registry semantics are NOT relaxed for tests. Production `add` is
     * first-registration-wins (see `registry.js`); forcing every add here made
     * the suite last-registration-wins, which does not merely loosen the rule,
     * it INVERTS it — a duplicate registration keeps the other entry than the
     * one production keeps. Bugs in that exact class (two envs each starting
     * the same service, an addon colliding with a core key) could therefore
     * pass their test while doing the opposite in the browser, and a test
     * written to pin the correct behaviour was structurally unable to fail.
     *
     * Tests that legitimately need to replace an entry pass `{ force: true }`
     * themselves, which is also what an addon does in production.
     */

    const translationModule = loader.modules.get("@web/core/translation");
    if (translationModule?.translatedTerms && translationModule.translationLoaded) {
        translationModule.translatedTerms[translationModule.translationLoaded] = true;
    }

    const userModule = loader.modules.get("@web/core/user");
    if (userModule?.user && userModule._makeUser) {
        onServerStateChange(userModule.user, () =>
            userModule._makeUser(makeSession(serverState)),
        );
    }

    const sessionModule = loader.modules.get("@web/session");
    if (sessionModule?.session) {
        onServerStateChange(sessionModule.session, () => makeSession(serverState));
    }

    function trackTestListeners(target) {
        const origAdd = target.addEventListener;
        const origRemove = target.removeEventListener;
        let trackedListeners = null;
        target.addEventListener = function (type, listener, options) {
            if (trackedListeners) {
                trackedListeners.push({ type, listener, options });
            }
            return origAdd.call(target, type, listener, options);
        };
        target.removeEventListener = function (type, listener, options) {
            if (trackedListeners) {
                const i = trackedListeners.findIndex(
                    (t) => t.type === type && t.listener === listener,
                );
                if (i >= 0) {
                    trackedListeners.splice(i, 1);
                }
            }
            return origRemove.call(target, type, listener, options);
        };
        beforeEach(
            () => {
                trackedListeners = [];
            },
            { global: true },
        );
        afterEach(
            () => {
                if (!trackedListeners) {
                    return;
                }
                for (const { type, listener, options } of trackedListeners) {
                    origRemove.call(target, type, listener, options);
                }
                trackedListeners = [];
            },
            { global: true },
        );
    }
    const browserModule = loader.modules.get("@web/core/browser/browser");
    if (browserModule?.browser) {
        trackTestListeners(browserModule.browser);
    }
    trackTestListeners(mockLocation);
    const rpcModule = loader.modules.get("@web/core/network/rpc");
    if (rpcModule?.rpcBus) {
        trackTestListeners(rpcModule.rpcBus);
    }
    const userBusModule = loader.modules.get("@web/core/user");
    if (userBusModule?.userBus) {
        trackTestListeners(userBusModule.userBus);
    }
    const routerModule = loader.modules.get("@web/core/browser/router");
    if (routerModule?.routerBus) {
        trackTestListeners(routerModule.routerBus);
    }
    const pagerModule = loader.modules.get("@web/components/pager/pager");
    if (pagerModule?.pagerBus) {
        trackTestListeners(pagerModule.pagerBus);
    }
    trackTestListeners(document.body);

    // `getFieldFromRegistry` dedups its "Missing widget" / "widget doesn't
    // support the type" warnings in a process-global Set, so the FIRST test to
    // resolve a broken arch claims the key and every later test asserting the
    // same warning sees silence — passing alone, vacuous in a full run. Looked
    // up lazily, like the buses above, so this file stays usable in bundles
    // that ship no field widgets.
    const fieldModule = loader.modules.get("@web/fields/field");
    if (fieldModule?.resetWidgetMissWarnings) {
        beforeEach(fieldModule.resetWidgetMissWarnings, { global: true });
    }

    // A `beforeinstallprompt` fired while no pwa service is running is parked
    // at module scope until one claims it, so an event a test never consumed
    // makes the NEXT test's service report an install prompt it never saw.
    const pwaModule = loader.modules.get("@web/ui/pwa/pwa_service");
    if (pwaModule?._resetPwaInstallPrompt) {
        beforeEach(pwaModule._resetPwaInstallPrompt, { global: true });
    }

    // `featureFlag` memoizes the parsed `?features=` overrides on first read.
    // That memo is derived from `browser.location` but outlives it, so
    // `patchWithCleanup(browser.location, ...)` — the correct way to install a
    // URL — cannot reach it: any earlier read pins the answer and the patching
    // test is silently told there are no overrides.
    const featureFlagsModule = loader.modules.get("@web/core/feature_flags");
    if (featureFlagsModule?._resetFeatureFlagsCache) {
        beforeEach(featureFlagsModule._resetFeatureFlagsCache, { global: true });
    }

    setupMockCurrencies(loader);

    setupMockTemplates(loader);

    const serviceReg = registryModule.registry?.category?.("services");
    if (!serviceReg) {
        return;
    }
    const content = serviceReg.content || {};
    for (const name of [
        "pos_data",
        "pos",
        "pos.printer",
        "pos.barcode_reader",
        "pos.bus",
        "pos_notification",
        "report",
        "preparation_display",
    ]) {
        delete content[name];
    }
}

export function clearServerModelCache() {
    serverModelCache.clear();
}

/**
 * @param {Iterable<string>} modelNames
 */
export async function fetchModelDefinitions(modelNames) {
    const namesList = [...modelsToFetch];
    if (namesList.length) {
        const formData = new FormData();
        formData.set("csrf_token", CSRF_TOKEN);
        formData.set("model_names", JSON.stringify(namesList));

        const response = await realFetch("/web/model/get_definitions", {
            body: formData,
            method: "POST",
        });
        if (!response.ok) {
            const [s, some, does] =
                namesList.length === 1
                    ? ["", "this", "does"]
                    : ["s", "some or all of these", "do"];
            const message = `Could not fetch definition${s} for server model${s} "${namesList.join(
                `", "`,
            )}": ${some} model${s} ${does} not exist`;
            throw new Error(message);
        }
        const modelDefs = await response.json();

        for (const [modelName, modelDef] of Object.entries(modelDefs)) {
            serverModelCache.set(modelName, freezeModel(modelDef));
            modelsToFetch.delete(modelName);
        }
    }

    const result = Object.create(null);
    for (const modelName of modelNames) {
        const cached = serverModelCache.get(modelName);
        if (cached) {
            result[modelName] = unfreezeModel(cached);
        }
    }
    return result;
}

/**
 * `mockLocation` names a host that does not exist, so any URL the application
 * absolutized against it — which is the correct thing for app code to do, the
 * bundle really is same-origin — cannot be fetched for real. This is the one
 * place that leaves the mock for the network, so it is the place that has to
 * undo the mock's own fiction: drop the mocked origin and let the request
 * resolve against the page actually serving the test.
 *
 * @param {string | URL} input
 * @returns {string}
 */
function unmockOrigin(input) {
    const raw = String(input);
    const mockOrigin = mockLocation.origin;
    if (mockOrigin && raw.startsWith(mockOrigin)) {
        return raw.slice(mockOrigin.length) || "/";
    }
    return raw;
}

/**
 * @param {string | URL} input
 * @param {RequestInit} [init]
 */
export function globalCachedFetch(input, init) {
    if (init?.method && init.method.toLowerCase() !== "get") {
        throw new Error(
            `cannot use a global cached fetch with HTTP method "${init.method}"`,
        );
    }
    const key = unmockOrigin(input);
    if (!(key in globalFetchCache)) {
        globalFetchCache[key] = realFetch(key, init).catch((reason) => {
            delete globalFetchCache[key];
            throw reason;
        });
    }
    return globalFetchCache[key].then((response) => response.clone());
}

/**
 * @param {string} modelName
 */
export function registerModelToFetch(modelName) {
    if (!serverModelCache.has(modelName)) {
        modelsToFetch.add(modelName);
    }
}

/**
 * Toned-down version of the RPC + ORM features since this file cannot depend on
 * them.
 *
 * @param {string} model
 * @param {string} method
 * @param {any[]} args
 * @param {Record<string, any>} kwargs
 */
export async function unmockedOrm(model, method, args, kwargs) {
    const response = await realFetch(`/web/dataset/call_kw/${model}/${method}`, {
        body: JSON.stringify({
            id: nextRpcId++,
            jsonrpc: "2.0",
            method: "call",
            params: { args, kwargs, method, model },
        }),
        headers: {
            "Content-Type": "application/json",
        },
        method: "POST",
    });
    const { error, result } = await response.json();
    if (error) {
        throw error;
    }
    return result;
}
