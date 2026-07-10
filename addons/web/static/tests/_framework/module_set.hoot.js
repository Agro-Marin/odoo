// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import { afterEach, beforeEach, globals } from "@odoo/hoot";

import { setupMockCurrencies } from "./mock_currency.hoot.js";
import { onServerStateChange, serverState } from "./mock_server_state.hoot.js";
import { makeSession } from "./mock_session.hoot.js";
import { setupMockTemplates } from "./mock_templates.hoot.js";

const { fetch: realFetch } = globals;

//-----------------------------------------------------------------------------
// Internal
//-----------------------------------------------------------------------------

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

//-----------------------------------------------------------------------------
// Constants
//-----------------------------------------------------------------------------

const CSRF_TOKEN = odoo.csrf_token;

/** @type {Record<string, Promise<Response>>} */
const globalFetchCache = Object.create(null);
/** @type {Set<string>} */
const modelsToFetch = new Set();
/** @type {Map<string, Record<string, unknown>>} */
const serverModelCache = new Map();

let nextRpcId = 1e9;

//-----------------------------------------------------------------------------
// Exports
//-----------------------------------------------------------------------------

/**
 * Prepare the test environment by patching registries and removing
 * app-specific services that crash without session state.
 *
 * Must be called BEFORE test modules are imported so that describe/test
 * calls don't encounter stale registry entries.
 */
export function setupTestEnvironment() {
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

    // 1b. Mark translations as loaded by default so OWL template
    //     compilation doesn't throw "translations have not been loaded"
    //     when a component with translatable text is mounted without
    //     the caller first invoking allowTranslations(). Restores the
    //     behaviour `legacy/patch_translations.js` provided to QUnit.
    //     Tests that need the un-loaded state can reset it explicitly.
    const translationModule = loader.modules.get("@web/core/l10n/translation");
    if (translationModule?.translatedTerms && translationModule.translationLoaded) {
        translationModule.translatedTerms[translationModule.translationLoaded] = true;
    }

    // 1c. Reset the ``user`` singleton between tests so its closure-bound
    //     ``groupCache`` / ``accessRightCache`` don't leak across tests.
    //     ``mock_user.hoot.js::mockUserFactory`` was the historical wiring
    //     point but is invoked nowhere in the current test bootstrap —
    //     without this hook, the first test calling
    //     ``user.hasGroup("base.group_allow_export")`` warms a cache that
    //     all later tests inherit, masking the ``has_group`` RPC that
    //     ``stepAllNetworkCalls`` + ``verifySteps`` are written to assert.
    const userModule = loader.modules.get("@web/services/user");
    if (userModule?.user && userModule._makeUser) {
        // ``_makeUser`` is destructive: it ``delete``s session keys after
        // destructuring them. Reusing the module-scoped ``session`` for
        // every reset would yield ``uid: undefined`` from the second test
        // onward, suppressing every cached call (e.g. ``hasGroup`` short-
        // circuits to ``Promise.resolve(false)``). Build a fresh mock
        // session from the current ``serverState`` on each cycle so the
        // recreated user always has a valid identity.
        onServerStateChange(userModule.user, () =>
            userModule._makeUser(makeSession(serverState)),
        );
    }

    // 1d. Sync the ``@web/session`` singleton with ``serverState`` between
    //     tests. Production code reads ``session.view_info[type]`` (e.g.
    //     ``view.js::loadView``), but ``patchWithCleanup(serverState.view_info, …)``
    //     doesn't propagate to the @web/session module without this wiring
    //     — the historical ``mockSessionFactory`` was meant to install it
    //     but is invoked nowhere. Without this, tests that register a new
    //     view type (e.g. view.test.js's ``toy``) hit
    //     ``Invalid view type: toy`` because the production lookup misses.
    const sessionModule = loader.modules.get("@web/session");
    if (sessionModule?.session) {
        onServerStateChange(sessionModule.session, () => makeSession(serverState));
    }

    // 1e. Auto-cleanup of ``addEventListener`` attachments per test on
    //     module-level event targets.
    //
    //     Odoo services have no destroy hook, so anything they bind to a
    //     module-singleton target (``browser``, the various ``*Bus``
    //     EventBus instances) persists for the lifetime of the page —
    //     across a unified test bundle that is many tests' worth of
    //     stale handlers.
    //
    //     Concrete failure caught in ``test_services``: ``hotkey_service``
    //     attaches a fresh ``onKeydown`` on every service start. Each
    //     closure captures its own ``registrations`` Map, but only the
    //     FIRST test's closure handles the keydown (others either also
    //     fire from stale closures or accumulate as dead handlers). When
    //     ``commandService`` registers ``control+k → openMainPalette`` in
    //     test N, the first test's stale ``hotkey_service`` is what fires
    //     on press.
    //
    //     The same shape catches ``currencyService`` on ``rpcBus``: each
    //     ``makeMockEnv`` registers a new ``RPC:RESPONSE`` listener, so
    //     by test N a single ``unlink`` triggers N reload-currencies
    //     calls (caught by ``currency_service.test.js::reload currencies
    //     when updating a res.currency``).  Same hazard exists for
    //     ``userBus``, ``routerBus``, ``pagerBus``.
    //
    //     This wraps each target's ``addEventListener`` to track calls
    //     during the test, and ``afterEach`` removes everything attached
    //     during it.  Listeners attached at MODULE LOAD (before the first
    //     beforeEach) leave ``trackedListeners === null`` and are NOT
    //     tracked — production listeners survive.
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
    // to for event delegation.  With no service destroy hook, those
    // capture-phase listeners persist across tests exactly like the bus
    // handlers above.
    //
    // Concrete failure this fixes: ``tooltip_service`` attaches a
    // ``mouseenter`` capture listener on ``document.body`` in ``whenReady``
    // and never removes it. Each test's tooltip service closes over ITS
    // env's ``popover`` service, so a test that mocks ``popover`` (e.g.
    // copy_clipboard's "Display a tooltip on click", whose CopyButton
    // triggers a real tooltip service start with the MOCK popover) leaves a
    // live body listener wired to that mock. A LATER test that hovers a
    // ``[data-tooltip]`` element (e.g. reference_field's "Product") fires the
    // stale listener, which schedules a tooltip open against the dead mock —
    // surfacing as an unexpected ``popover.add`` step in the wrong test.
    // HOOT itself binds no ``document.body`` listeners (it only appends the
    // fixture element), so tracking body is safe. Listeners attached at
    // MODULE LOAD stay untracked (``trackedListeners === null``) as with the
    // buses above.
    trackTestListeners(document.body);

    // 1f. Seed `@web/services/currency`'s in-memory `currencies` map
    //     from `serverState.currencies` so monetary widgets format with
    //     the expected currency symbol.  `mock_currency.hoot.js` was
    //     historically a dead module-factory — `setupMockCurrencies`
    //     rewrites it as a direct subscription.
    setupMockCurrencies(loader);

    // 1g. Rewrite every template's `<img src>` / `<iframe src>` to a
    //     static placeholder, moving the original value to `data-src`,
    //     so:
    //     - the browser never issues a real HTTP request for an asset
    //       Chrome's native loader can't be intercepted by the JS mock
    //       server (`_onRoute "/web/image/..."`),
    //     - tests can assert the computed URL via `data-src` without
    //       waiting for or fighting the network.
    //     `mock_templates.hoot.js` was historically a dead
    //     module-factory — `setupMockTemplates` rewrites it as a direct
    //     processor registration.
    setupMockTemplates(loader);

    // 2. Remove app-specific services that require runtime state
    //    not available in test context (e.g. pos_config_id).  These
    //    services would otherwise REGISTER successfully but then crash
    //    inside their ``start()`` body when they touch missing runtime
    //    state.  Deleting them here is a pre-emptive removal at the
    //    registry layer, distinct from the env.js cascade-skip which
    //    handles services whose declared deps are missing — both
    //    failure modes are guarded, at different layers.
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

    // Cascade-removal pass (formerly step 3) was deleted 2026-05-22.
    // It walked the registry at framework-init time and removed every
    // service with an unmet dep, attempting to prevent env.js's
    // ``startServices`` from throwing ``Some services could not be
    // started``.  The pass ran too early: test files lazy-load via
    // dynamic ``import()`` AFTER framework init, so services
    // registered by those imports (e.g. ``spreadsheet_dashboard_loader``
    // via ``dashboard_loader.test.js``) slipped past the cascade and
    // re-introduced the startup error every time ``startServices``
    // hit them.  env.js now runs the same cascade at startServices
    // time, when the registry is complete, so this pre-pass is
    // redundant and was removed.  See env.js cascade-skip block
    // (search for ``// Cascade-skip services whose declared
    // dependencies cannot be met``).
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
