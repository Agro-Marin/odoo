// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import { afterEach, beforeEach, globals, onError } from "@odoo/hoot";

import { setupMockCurrencies } from "./mock_currency.hoot.js";
import { onServerStateChange, serverState } from "./mock_server_state.hoot.js";
import { makeSession } from "./mock_session.hoot.js";
import { setupMockTemplates } from "./mock_templates.hoot.js";

const { fetch: realFetch } = globals;

// Internal

/**
 * @param {Record<any, any>} object
 */
function clearObject(object) {
    for (const key in object) {
        delete object[key];
    }
}

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

// Constants

const CSRF_TOKEN = odoo.csrf_token;

/** @type {Record<string, Promise<Response>>} */
const globalFetchCache = Object.create(null);
/** @type {Set<string>} */
const modelsToFetch = new Set();
/** @type {Map<string, Record<string, unknown>>} */
const serverModelCache = new Map();

let nextRpcId = 1e9;

// Exports

/**
 * Prepare the test environment by patching registries and removing
 * app-specific services that crash without session state.
 *
 * Must be called BEFORE test modules are imported so that describe/test
 * calls don't encounter stale registry entries.
 */
export function setupTestEnvironment() {
    // 0. Globally swallow SupersededError, mirroring production: the action
    //    service's KeepLast (rejectSuperseded mode) rejects a doAction /
    //    navigation superseded by a newer one with a SupersededError, which the
    //    error service swallows silently (no dialog, no console). Supersession
    //    is a normal control-flow signal, never a test failure — so any test
    //    that triggers it (the concurrency suite, rapid navigation, pivot/list
    //    reloads...) must not fail on the resulting unhandled rejection. Match
    //    by name (not instanceof) to avoid importing a non-".hoot" module.
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

    // 1. Allow re-adding registry keys (tests overwrite production entries).
    const origAdd = registryModule.Registry.prototype.add;
    registryModule.Registry.prototype.add = function (key, value, options = {}) {
        return origAdd.call(this, key, value, { ...options, force: true });
    };

    // 1b. Mark translations as loaded by default so mounting a component with
    //     translatable text doesn't throw "translations have not been loaded"
    //     (behaviour `legacy/patch_translations.js` provided to QUnit). Tests
    //     needing the un-loaded state can reset it explicitly.
    const translationModule = loader.modules.get("@web/core/l10n/translation");
    if (translationModule?.translatedTerms && translationModule.translationLoaded) {
        translationModule.translatedTerms[translationModule.translationLoaded] = true;
    }

    // 1c. Reset the ``user`` singleton between tests so its closure-bound
    //     ``groupCache`` / ``accessRightCache`` don't leak across tests —
    //     otherwise the first ``user.hasGroup(...)`` call warms a cache that
    //     all later tests inherit, masking the ``has_group`` RPC that
    //     ``stepAllNetworkCalls`` + ``verifySteps`` are written to assert.
    const userModule = loader.modules.get("@web/services/user");
    if (userModule?.user && userModule._makeUser) {
        // ``_makeUser`` deletes session keys after destructuring them, so
        // reusing the module-scoped ``session`` on every reset would yield
        // ``uid: undefined`` from the second test onward. Build a fresh mock
        // session from ``serverState`` each cycle instead.
        onServerStateChange(userModule.user, () =>
            userModule._makeUser(makeSession(serverState)),
        );
    }

    // 1d. Sync the ``@web/session`` singleton with ``serverState`` between
    //     tests: production code reads ``session.view_info[type]`` (e.g.
    //     ``view.js::loadView``), but ``patchWithCleanup(serverState.view_info, …)``
    //     doesn't propagate there without this wiring. Without it, tests
    //     registering a new view type (e.g. view.test.js's ``toy``) hit
    //     ``Invalid view type: toy``.
    const sessionModule = loader.modules.get("@web/session");
    if (sessionModule?.session) {
        onServerStateChange(sessionModule.session, () => makeSession(serverState));
    }

    // 1e. Auto-cleanup of ``addEventListener`` attachments per test on
    //     module-level event targets (``browser``, the various ``*Bus``
    //     EventBus instances). Odoo services have no destroy hook, so
    //     listeners they bind to these singletons persist for the whole
    //     unified test bundle — e.g. ``hotkey_service`` re-attaches
    //     ``onKeydown`` on every service start, but only the first test's
    //     stale closure ends up firing; ``currencyService`` on ``rpcBus``
    //     similarly accumulates one reload-currencies call per test (same
    //     hazard on ``userBus``, ``routerBus``, ``pagerBus``).
    //
    //     Wraps each target's ``addEventListener`` to track calls during the
    //     test; ``afterEach`` removes everything attached during it.
    //     Listeners attached at MODULE LOAD (before the first beforeEach)
    //     leave ``trackedListeners === null`` and are NOT tracked —
    //     production listeners survive.
    function trackTestListeners(target) {
        const origAdd = target.addEventListener;
        const origRemove = target.removeEventListener;
        let trackedListeners = null;
        // ``.call(target, ...)`` is required for unbound prototype methods
        // (EventTarget); ``browser.addEventListener`` is already bound to
        // ``window`` so its ``this`` is irrelevant — both work uniformly.
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
    const rpcModule = loader.modules.get("@web/core/network/rpc");
    if (rpcModule?.rpcBus) {
        trackTestListeners(rpcModule.rpcBus);
    }
    const userBusModule = loader.modules.get("@web/services/user");
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
    // ``document.body`` is the other module-singleton target services bind
    // to for event delegation, with the same cross-test leak: e.g.
    // ``tooltip_service`` attaches a ``mouseenter`` capture listener in
    // ``whenReady`` and never removes it, so a test that mocks ``popover``
    // (e.g. copy_clipboard's "Display a tooltip on click") leaves a stale
    // listener wired to the dead mock, which a LATER hover test (e.g.
    // reference_field's "Product") can trigger. HOOT itself binds no
    // ``document.body`` listeners, so tracking body is safe.
    trackTestListeners(document.body);

    // 1f. Seed `@web/services/currency`'s in-memory `currencies` map from
    //     `serverState.currencies` so monetary widgets format with the
    //     expected currency symbol.
    setupMockCurrencies(loader);

    // 1g. Rewrite every template's `<img src>` / `<iframe src>` to a static
    //     placeholder, moving the original value to `data-src`: avoids real
    //     HTTP requests the mock server can't intercept, and lets tests
    //     assert the computed URL via `data-src` without fighting the
    //     network.
    setupMockTemplates(loader);

    // 2. Remove app-specific services that require runtime state not
    //    available in test context (e.g. pos_config_id): they would
    //    otherwise REGISTER successfully but crash inside `start()` when
    //    they touch missing state. Distinct from the env.js cascade-skip,
    //    which handles services whose declared deps are missing.
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

    // Cascade-removal pass (formerly step 3) was deleted 2026-05-22: it ran
    // too early, at framework-init time, so services registered later via
    // dynamic `import()` (e.g. `spreadsheet_dashboard_loader`) slipped past
    // it and still hit env.js's "Some services could not be started". env.js
    // now runs the same cascade at startServices time, when the registry is
    // complete — see its "Cascade-skip services whose declared dependencies
    // cannot be met" block.
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
 * @param {RequestInit} [init]
 */
export function globalCachedFetch(input, init) {
    if (init?.method && init.method.toLowerCase() !== "get") {
        throw new Error(
            `cannot use a global cached fetch with HTTP method "${init.method}"`,
        );
    }
    const key = String(input);
    if (!(key in globalFetchCache)) {
        globalFetchCache[key] = realFetch(input, init).catch((reason) => {
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
