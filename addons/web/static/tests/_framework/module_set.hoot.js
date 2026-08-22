// @ts-check

import { afterEach, beforeEach, globals, mockLocation, onError } from "@odoo/hoot";

import { setupMockCurrencies } from "./mock_currency.hoot.js";
import { onServerStateChange, serverState } from "./mock_server_state.hoot.js";
import { makeSession } from "./mock_session.hoot.js";
import { setupMockTemplates } from "./mock_templates.hoot.js";

const { fetch: realFetch } = globals;

/**
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

    const R_OWL_SYNTHETIC_LISTENER = /\bnativeToSyntheticEvent\b/;

    function trackTestListeners(target) {
        const origAdd = target.addEventListener;
        const origRemove = target.removeEventListener;
        let trackedListeners = null;
        target.addEventListener = function (type, listener, options) {
            if (trackedListeners && !R_OWL_SYNTHETIC_LISTENER.test(String(listener))) {
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
    trackTestListeners(window);
    trackTestListeners(document);
    trackTestListeners(document);
    trackTestListeners(document.body);

    const fieldModule = loader.modules.get("@web/fields/field");
    if (fieldModule?.resetWidgetMissWarnings) {
        beforeEach(fieldModule.resetWidgetMissWarnings, { global: true });
    }

    const pwaModule = loader.modules.get("@web/ui/pwa/pwa_service");
    if (pwaModule?._resetPwaInstallPrompt) {
        beforeEach(pwaModule._resetPwaInstallPrompt, { global: true });
    }

    const featureFlagsModule = loader.modules.get("@web/core/feature_flags");
    if (featureFlagsModule?._resetFeatureFlagsCache) {
        beforeEach(featureFlagsModule._resetFeatureFlagsCache, { global: true });
    }

    const viewportModule = loader.modules.get("@web/ui/viewport");
    if (viewportModule?._resetMediaQueryLists) {
        beforeEach(viewportModule._resetMediaQueryLists, { global: true });
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
