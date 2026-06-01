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
        // The previous test's ``after()`` cleanup didn't flip
        // ``currentEnv`` back to null — typically because that test
        // failed at setup before the cleanup registration ran.
        // Reset instead of throwing so the next test can start
        // cleanly; otherwise this single dangling reference
        // cascades into every subsequent test failing the same way.
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

            // Ideally: should be done in a patch of the localization service, but this
            // is less intrusive for now.
            //
            // Clear the cached translation values so the next test starts
            // with a fresh slate, but KEEP ``[translationLoaded] = true``.
            // ``setupTestEnvironment`` sets the flag once at bundle load
            // and any subsequent ``_t(...)`` call expects it to remain
            // truthy — without this, every test after the first one
            // throws "Cannot translate string: translations have not
            // been loaded" the moment a plugin builds a template that
            // contains a lazy ``_t(…)`` substitution (e.g. the
            // html_editor ``movenode_plugin``'s ``setMovableElement``
            // tooltip), which manifested as the 12 checklist failures
            // and other html_editor regressions.
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

    // Drop the per-env UPDATE listener that startServices installs on the
    // singleton service registry. Registered BEFORE the ``await
    // startServices(env)`` call so that even if startServices throws
    // (e.g. tests that assert a crashing service factory rejects
    // makeMockEnv), the cleanup still runs at end-of-test. startServices
    // assigns ``env.disposeServiceRegistryListener`` before the await
    // that can throw, so the optional-call here resolves to a real
    // dispose function in every reachable failure mode.
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
                        service.then((value) => patch(value, serviceFactory));
                    } else {
                        patch(service, serviceFactory);
                    }
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
            patch(currentEnv.services[name], serviceFactory);
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
