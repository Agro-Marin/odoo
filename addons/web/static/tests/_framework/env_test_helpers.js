// @ts-check

import { after, afterEach, beforeEach, registerDebugInfo } from "@odoo/hoot";
import { startRouter } from "@web/core/browser/router";
import {
    translatedTerms,
    translatedTermsGlobal,
    translationLoaded,
} from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { pick } from "@web/core/utils/collections/objects";
import { patch } from "@web/core/utils/patch";
import { makeEnv, startServices } from "@web/env";
import { createDebugContext } from "@web/services/debug/debug_context";

import { makeMockServer, MockServer } from "./mock_server/mock_server.js";

/**
 * @typedef {Record<keyof Services, any>} Dependencies
 *
 * @typedef {import("@web/env").OdooEnv} OdooEnv
 *
 * @typedef {import("@web/core/registry").Registry} Registry
 *
 * @typedef {import("services").ServiceFactories} Services
 */

//-----------------------------------------------------------------------------
// Internals
//-----------------------------------------------------------------------------

/**
 * TODO: remove when services do not have side effects anymore
 * This forsaken block of code ensures that all are properly cleaned up after each
 * test because they were populated during the starting process of some services.
 *
 * @param {Registry} registry
 */
const registerRegistryForCleanup = (registry) => {
    const content = Object.entries(registry.content).map(([key, value]) => [
        key,
        value.slice(),
    ]);
    registriesContent.set(registry, content);

    for (const subRegistry of Object.values(registry.subRegistries)) {
        registerRegistryForCleanup(subRegistry);
    }
};

const registriesContent = new WeakMap();
/** @type {OdooEnv | null} */
let currentEnv = null;

// Registers all registries for cleanup in all tests.
// { global: true } is required because this runs at module top-level
// (outside any describe() suite) in ESM native mode.
beforeEach(() => registerRegistryForCleanup(registry), { global: true });
afterEach(() => restoreRegistry(registry), { global: true });

//-----------------------------------------------------------------------------
// Exports
//-----------------------------------------------------------------------------

/**
 * Empties the given registry.
 *
 * @param {Registry} registry
 */
export function clearRegistry(registry) {
    registry.content = {};
    registry.elements = null;
    registry.entries = null;
}

export function getMockEnv() {
    return currentEnv;
}

/**
 * @template {keyof Services} T
 * @param {T} name
 * @returns {Services[T]}
 */
export function getService(name) {
    return currentEnv.services[name];
}

/**
 * Makes a mock environment along with a mock server
 *
 * @param {Partial<OdooEnv>} [partialEnv]
 * @param {{
 *  makeNew?: boolean;
 * }} [options]
 */
export async function makeMockEnv(partialEnv, options) {
    if (currentEnv && !options?.makeNew) {
        // Previous test's after() cleanup didn't run (e.g. failed before
        // registering it). Reset instead of throwing so this dangling
        // reference doesn't cascade into every subsequent test.
        currentEnv = null;
    }

    if (!MockServer.current) {
        await makeMockServer();
    }

    const env = makeEnv();
    Object.assign(env, partialEnv, createDebugContext(/** @type {any} */ (env))); // This is needed if the views are in debug mode

    registerDebugInfo("env", env);

    if (!currentEnv) {
        currentEnv = env;
        startRouter();
        after(() => {
            currentEnv = null;

            // Ideally this belongs in a patch of the localization service, but this is
            // less intrusive for now. Clear cached translations for the next test but
            // KEEP [translationLoaded] = true: setupTestEnvironment sets it once at
            // bundle load and lazy _t(...) calls (e.g. html_editor's movenode_plugin
            // tooltip) expect it to stay truthy, or every test after the first throws.
            if (translatedTerms[translationLoaded]) {
                for (const key in translatedTerms) {
                    delete translatedTerms[key];
                }
                for (const key in translatedTermsGlobal) {
                    delete translatedTermsGlobal[key];
                }
                translatedTerms[translationLoaded] = true;
            }
        });
    }

    // Drop the per-env UPDATE listener startServices installs on the singleton
    // service registry. Registered before the await so cleanup still runs even
    // if startServices throws (it assigns disposeServiceRegistryListener before
    // the point where it can reject).
    after(() => env.disposeServiceRegistryListener?.());

    await startServices(env);

    return env;
}

/**
 * Makes a mock environment for dialog tests
 *
 * @param {Partial<OdooEnv>} [partialEnv]
 * @returns {Promise<OdooEnv>}
 */
export async function makeDialogMockEnv(partialEnv) {
    return makeMockEnv({
        ...partialEnv,
        dialogData: {
            close: () => {},
            isActive: true,
            scrollToOrigin: () => {},
            ...partialEnv?.dialogData,
        },
    });
}

/**
 * @template {keyof Services} T
 * @param {T} name
 * @param {Partial<Services[T]> |
 *  ((env: OdooEnv, dependencies: Dependencies) => Services[T])
 * } serviceFactory
 */
export function mockService(name, serviceFactory) {
    const serviceRegistry = registry.category("services");
    const originalService = serviceRegistry.get(name, null);
    // ``patch()`` extensions are single-use: it mutates the extension in place
    // (re-parenting it via ``setPrototypeOf`` to wire the ``super`` chain), and
    // that re-parenting is precisely what makes ``super.method(...)`` inside an
    // object-literal mock resolve to the original service. So the extension
    // MUST be ``serviceFactory`` itself — a descriptor-clone would carry the
    // methods (whose ``[[HomeObject]]`` is the original literal) but leave their
    // ``super`` pointing at the un-reparented original, silently breaking it.
    // The start wrapper can still run more than once for the same factory (the
    // forced registry entry outlives its test; later ``startServices`` calls
    // replay it), so instead of cloning we release the previous application
    // before re-patching and register a test-teardown ``after`` — a
    // single-use extension is fine as long as it is unpatched between uses.
    let unpatch = null;
    const applyMock = (service) => {
        unpatch?.();
        unpatch = patch(service, serviceFactory);
        after(() => {
            unpatch?.();
            unpatch = null;
        });
    };
    serviceRegistry.add(
        name,
        {
            ...originalService,
            start(env, dependencies) {
                if (typeof serviceFactory === "function") {
                    return serviceFactory(env, dependencies);
                } else {
                    const service = originalService.start(env, dependencies);
                    if (service instanceof Promise) {
                        return service.then((value) => {
                            applyMock(value);
                            return value;
                        });
                    }
                    applyMock(service);
                    return service;
                }
            },
        },
        { force: true },
    );

    // Patch already initialized service
    if (currentEnv?.services?.[name]) {
        if (typeof serviceFactory === "function") {
            const dependencies = pick(
                currentEnv.services,
                .../** @type {any[]} */ (originalService.dependencies || []),
            );
            /** @type {any} */ (currentEnv.services)[name] = serviceFactory(
                currentEnv,
                /** @type {any} */ (dependencies),
            );
        } else {
            applyMock(currentEnv.services[name]);
        }
    }
}

/**
 * @param {Registry} registry
 */
export function restoreRegistry(registry) {
    if (registriesContent.has(registry)) {
        clearRegistry(registry);

        registry.content = Object.fromEntries(registriesContent.get(registry));
    }

    for (const subRegistry of Object.values(registry.subRegistries)) {
        restoreRegistry(subRegistry);
    }
}
