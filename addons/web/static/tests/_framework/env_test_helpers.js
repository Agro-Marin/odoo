// @ts-check

import { after, afterEach, beforeEach, registerDebugInfo } from "@odoo/hoot";
import { startRouter } from "@web/core/browser/router";
import { createDebugContext } from "@web/core/debug/debug_context";
import { registry } from "@web/core/registry";
import {
    translatedTerms,
    translatedTermsGlobal,
    translationLoaded,
} from "@web/core/translation";
import { pick } from "@web/core/utils/collections/objects";
import { patch } from "@web/core/utils/patch";
import { makeEnv, startServices } from "@web/env";

/** @import { OdooEnv } from "@web/env" */
import { makeMockServer, MockServer } from "./mock_server/mock_server.js";

/**
 * @typedef {Record<keyof Services, any>} Dependencies
 * @typedef {import("@web/env").OdooEnv} OdooEnv
 * @typedef {import("@web/core/registry").Registry} Registry
 * @typedef {import("services").ServiceFactories} Services
 */

/**
 * Snapshot a registry so `restoreRegistry` can put it back. Exported alongside
 * its two halves so a test can exercise the round trip on a registry of its own.
 *
 * @param {Registry} registry
 */
export const registerRegistryForCleanup = (registry) => {
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
/** @type {OdooEnv | null} */
let currentEnv = null;

beforeEach(() => registerRegistryForCleanup(registry), { global: true });
afterEach(() => restoreRegistry(registry), { global: true });

/**
 * @param {Registry} registry
 */
export function clearRegistry(registry) {
    // Object.create(null), not {}: Registry looks keys up with `key in content`
    // and `content[key]`, both of which walk the prototype chain. A plain object
    // makes the registry answer for every member of Object.prototype -- a field
    // widget named "toString" would resolve to Object.prototype.toString instead
    // of raising KeyNotFoundError. Production builds it the same way
    // (core/registry.js); a test harness that does not is a harness that can
    // pass where the real thing would throw.
    registry.content = Object.create(null);
    registry.elements = null;
    registry.entries = null;
}

/**
 * The environment of the running test. Only meaningful inside one, where
 * `makeMockEnv` has set it -- `getService` below dereferences it with no guard
 * for the same reason, and 33 call sites read `.bus` or `.services` straight
 * off this. Declaring it nullable here would push a check into every one of
 * them for a case none of them can reach.
 *
 * @returns {OdooEnv}
 */
export function getMockEnv() {
    return /** @type {OdooEnv} */ (currentEnv);
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
 * @param {Partial<OdooEnv>} [partialEnv]
 * @param {{
 * makeNew?: boolean;
 * }} [options]
 */
export async function makeMockEnv(partialEnv, options) {
    if (currentEnv && !options?.makeNew) {
        currentEnv = null;
    }

    if (!MockServer.current) {
        await makeMockServer();
    }

    const env = makeEnv();
    Object.assign(env, partialEnv, createDebugContext(/** @type {any} */ (env)));

    registerDebugInfo("env", env);

    if (!currentEnv) {
        currentEnv = env;
        startRouter();
        after(() => {
            currentEnv = null;

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

    after(() => env.destroy?.());

    await startServices(env);

    return env;
}

/**
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
 * ((env: OdooEnv, dependencies: Dependencies) => Services[T])
 * } serviceFactory
 */
export function mockService(name, serviceFactory) {
    const serviceRegistry = registry.category("services");
    const originalService = serviceRegistry.get(name, null);
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

        // Assign into the null-prototype object clearRegistry just made rather
        // than replacing it with Object.fromEntries's plain one.
        Object.assign(
            registry.content,
            Object.fromEntries(registriesContent.get(registry)),
        );
    }

    for (const subRegistry of Object.values(registry.subRegistries)) {
        restoreRegistry(subRegistry);
    }
}
