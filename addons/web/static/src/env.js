// @ts-check
/** @odoo-module */

/** @module @web/env - OWL environment factory, service dependency resolution, and app mounting */

import { App, EventBus } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { appTranslateFn } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { findDependencyCycle } from "@web/core/utils/dependency_graph";
import { SERVICES_METADATA } from "@web/core/utils/hooks";
import { session } from "@web/session";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

/**
 * @typedef {{
 *  bus: EventBus;
 *  debug: string;
 *  services: import("services").ServiceFactories;
 *  readonly isSmall: boolean;
 *  config?: Record<string, any>;
 *  [key: string]: any;
 * }} OdooEnv
 */

// -----------------------------------------------------------------------------
// makeEnv
// -----------------------------------------------------------------------------

/**
 * Return a value Odoo Env object
 *
 * @returns {OdooEnv}
 */
export function makeEnv() {
    const bus = new EventBus();
    const prom = new Promise((resolve) => {
        bus.addEventListener("SERVICES-LOADED", resolve, { once: true });
    });
    return /** @type {any} */ ({
        bus,
        isReady: prom,
        services: {},
        debug: odoo.debug,
        get isSmall() {
            throw new Error("UI service not initialized!");
        },
    });
}

// -----------------------------------------------------------------------------
// Service Launcher
// -----------------------------------------------------------------------------

const serviceRegistry = registry.category("services");

serviceRegistry.addValidation({
    start: Function,
    dependencies: { type: Array, element: String, optional: true },
    async: {
        type: [{ type: Array, element: String }, { value: true }],
        optional: true,
    },
    "*": true,
});

let startServicesPromise = null;

/**
 * Start all services registered in the service registry, while making sure
 * each service dependencies are properly fulfilled.
 *
 * @param {OdooEnv} env
 * @returns {Promise<void>}
 */
export async function startServices(env) {
    // Wait for all synchronous code so that if new services that depend on
    // one another are added to the registry, they're all present before we
    // start them regardless of the order they're added to the registry.
    await Promise.resolve();

    const toStart = new Map();
    serviceRegistry.addEventListener("UPDATE", async (ev) => {
        // Wait for all synchronous code so that if new services that depend on
        // one another are added to the registry, they're all present before we
        // start them regardless of the order they're added to the registry.
        await Promise.resolve();
        const { operation, key: name, value: service } = ev.detail;
        if (operation === "delete") {
            // We hardly see why it would be useful to remove a service.
            // Furthermore we could encounter problems with dependencies.
            // Keep it simple!
            return;
        }
        if (toStart.size) {
            const namedService = Object.assign(Object.create(service), {
                name,
            });
            toStart.set(name, namedService);
        } else {
            await _startServices(env, toStart);
        }
    });
    await _startServices(env, toStart);
}

/**
 * Start all services in `toStart`, resolving dependencies with O(N+E)
 * dependency-counting and reverse-edge propagation.
 *
 * Services are started in waves: each wave starts all services whose
 * dependencies are met, waits for their (possibly async) results, then
 * propagates to unlock the next wave.
 *
 * @param {OdooEnv} env
 * @param {Map<string, any>} toStart
 */
async function _startServices(env, toStart) {
    if (startServicesPromise) {
        return startServicesPromise.then(() => _startServices(env, toStart));
    }
    const services = env.services;
    for (const [name, service] of serviceRegistry.getEntries()) {
        if (!(name in services)) {
            const namedService = Object.assign(Object.create(service), {
                name,
            });
            toStart.set(name, namedService);
        }
    }

    // --- O(N+E) dependency resolution state ---

    /** Count of unmet deps per pending service. @type {Map<string, number>} */
    const _pendingDeps = new Map();
    /** Reverse graph: dep name → services waiting on it. @type {Map<string, Set<string>>} */
    const _dependents = new Map();
    /** Services with all deps met, ready to start. @type {string[]} */
    const _readyQueue = [];

    /**
     * Register a service for dependency tracking and enqueue if ready.
     * Idempotent — skips services already tracked.
     * @param {string} name
     */
    function _trackService(name) {
        if (_pendingDeps.has(name)) {
            return;
        }
        const service = toStart.get(name);
        if (!service) {
            return;
        }
        let pending = 0;
        for (const dep of service.dependencies || []) {
            if (!(dep in services)) {
                let waiters = _dependents.get(dep);
                if (!waiters) {
                    waiters = new Set();
                    _dependents.set(dep, waiters);
                }
                // Dedup: only count each unique dep once per service
                if (!waiters.has(name)) {
                    waiters.add(name);
                    pending++;
                }
            }
        }
        _pendingDeps.set(name, pending);
        if (pending === 0) {
            _readyQueue.push(name);
        }
    }

    /**
     * Propagate: a service has loaded — decrement pending count for all
     * dependents, enqueuing any that reach zero.
     * @param {string} name
     */
    function _propagate(name) {
        const waiters = _dependents.get(name);
        if (waiters) {
            for (const waiter of waiters) {
                const remaining = _pendingDeps.get(waiter);
                if (remaining !== undefined) {
                    const count = remaining - 1;
                    _pendingDeps.set(waiter, count);
                    if (count === 0) {
                        _readyQueue.push(waiter);
                    }
                }
            }
            _dependents.delete(name);
        }
    }

    // Initial tracking
    for (const name of toStart.keys()) {
        _trackService(name);
    }

    // Start services in waves: each wave starts all ready services in
    // parallel, waits for their results, then propagates to dependents.
    async function start() {
        // Track any new services added via registry UPDATE listener
        for (const name of toStart.keys()) {
            _trackService(name);
        }

        const proms = [];
        while (_readyQueue.length) {
            const name = _readyQueue.pop();
            if (name in services) {
                continue;
            }
            const service = toStart.get(name);
            if (!service) {
                continue;
            }
            toStart.delete(name);
            _pendingDeps.delete(name);
            const entries = (service.dependencies || []).map((dep) => [
                dep,
                services[dep],
            ]);
            const dependencies = Object.fromEntries(entries);
            const value = service.start(env, dependencies);
            if ("async" in service) {
                SERVICES_METADATA[name] = service.async;
            }
            proms.push(
                Promise.resolve(value).then((val) => {
                    services[name] = val || null;
                    _propagate(name);
                }),
            );
        }
        await Promise.all(proms);
        if (proms.length) {
            return start();
        }
    }
    startServicesPromise = start().finally(() => {
        startServicesPromise = null;
    });
    await startServicesPromise;
    if (toStart.size) {
        const missingDeps = new Set();
        for (const service of toStart.values()) {
            for (const dependency of service.dependencies || []) {
                if (!(dependency in services) && !toStart.has(dependency)) {
                    missingDeps.add(dependency);
                }
            }
        }
        if (missingDeps.size) {
            throw new Error(
                `Some services could not be started: ${[...toStart.keys()]}. ` +
                    `Missing dependencies: ${[...missingDeps].join(", ")}`,
            );
        }
        // All deps exist but couldn't start — must be a circular dependency
        const depGraph = new Map();
        for (const [name, service] of toStart) {
            depGraph.set(name, service.dependencies || []);
        }
        const cycle = findDependencyCycle(depGraph);
        const cycleInfo = cycle
            ? cycle.join(" \u2192 ")
            : [...toStart.keys()].join(", ");
        throw new Error(`Circular service dependency detected: ${cycleInfo}`);
    }
    env.bus.trigger("SERVICES-LOADED");
}

export const customDirectives = {
    // t-custom-click="handler"
    // This custom directive adds two event listeners ("click"; "auxclick") and calls the global value "click".
    // The global value "click" calls the handler with two parameters:
    //      - ev (the original event)
    //      - isMiddleClick (boolean: user middle-clicked or ctrl+clicked)
    //
    // "stop" and "prevent" modifiers are resolved at compile time into boolean
    // flags, avoiding runtime JSON.parse + array iteration on every click.
    click: (node, value, modifiers) => {
        let mods = "";
        if (modifiers.includes("synthetic")) {
            mods += ".synthetic";
        }
        if (modifiers.includes("capture")) {
            mods += ".capture";
        }
        const hasStop = modifiers.includes("stop");
        const hasPrevent = modifiers.includes("prevent");
        const handlerFunction = `(ev) => __globals__.click(ev, (${value}).bind(this), ${hasStop}, ${hasPrevent})`;
        node.setAttribute(`t-on-click${mods}`, handlerFunction);
        node.setAttribute(`t-on-auxclick${mods}`, handlerFunction);
    },
};

export const globalValues = {
    /** @param {MouseEvent} ev @param {Function} value @param {boolean} hasStop @param {boolean} hasPrevent */
    click: (ev, value, hasStop, hasPrevent) => {
        if (ev.button === 0 || ev.button === 1) {
            if (hasStop) {
                ev.stopPropagation();
            }
            if (hasPrevent) {
                ev.preventDefault();
            }
            const ctrlKey = isMacOS() ? ev.metaKey : ev.ctrlKey;
            const isMiddleClick = (ctrlKey && ev.button === 0) || ev.button === 1;
            return value(ev, isMiddleClick);
        }
    },
};

/**
 * Create an application with a given component as root and mount it. If no env
 * is provided, the application will be treated as a "root": an env will be
 * created and the services will be started, it will also be set as the root
 * in `__WOWL_DEBUG__`
 *
 * @param {import("@odoo/owl").Component} component the component to mount
 * @param {HTMLElement} target the HTML element in which to mount the app
 * @param {Partial<ConstructorParameters<typeof App>[1]>} [appConfig] object
 *  containing a (partial) config for the app.
 */
export async function mountComponent(component, target, appConfig = {}) {
    let { env } = appConfig;
    const isRoot = !env;
    if (isRoot) {
        env = makeEnv();
        await startServices(/** @type {OdooEnv} */ (env));
    }
    const app = new App(/** @type {any} */ (component), {
        env,
        getTemplate,
        dev: /** @type {any} */ (env).debug || session.test_mode,
        warnIfNoStaticProps: !session.test_mode,
        name: component.name,
        translatableAttributes: ["data-tooltip"],
        translateFn: appTranslateFn,
        customDirectives,
        globalValues,
        ...appConfig,
    });
    const root = await app.mount(target);
    if (isRoot) {
        /** @type {any} */ (odoo).__WOWL_DEBUG__ = { root };
    }
    return app;
}
