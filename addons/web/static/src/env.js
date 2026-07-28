// @ts-check
/** @odoo-module native */

/** @module @web/env - OWL environment factory, service dependency resolution, and app mounting */

import { App, EventBus } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { AppEvent } from "@web/core/events";
import { appTranslateFn } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { makeAssetLog } from "@web/core/utils/asset_log";
import {
    createWaveResolver,
    findDependencyCycle,
} from "@web/core/utils/dependency_graph";
import { SERVICES_METADATA } from "@web/core/utils/hooks";
import { session } from "@web/session";

const log = makeAssetLog("env");

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

/**
 * Return a value Odoo Env object
 *
 * @returns {OdooEnv}
 */
export function makeEnv() {
    log("makeEnv: creating OdooEnv — debug=", odoo.debug || "(empty)");
    const bus = new EventBus();
    const prom = new Promise((resolve) => {
        bus.addEventListener(AppEvent.SERVICES_LOADED, resolve, { once: true });
    });
    return /** @type {any} */ ({
        bus,
        isReady: prom,
        services: {},
        debug: odoo.debug,
        get isSmall() {
            throw new Error("UI service not initialized!");
        },
        /**
         * Service-teardown contract. Disposes the singleton-registry UPDATE
         * listener this env installed, then calls each started service's
         * optional ``destroy()`` so services holding process-global resources
         * (rpcBus listeners, timers, body event listeners) release them.
         *
         * Production creates one page-lived env and never destroys it (no-op
         * there); test infra and embedded/sub-app envs call this on cleanup to
         * stop leaked listeners from firing against a dead env — the root cause
         * behind the ``slow_rpc`` / ``result_set_cache_invalidator`` rpcBus
         * leaks and the previously-unreachable ``tooltip`` disposer.
         */
        destroy() {
            this.disposeServiceRegistryListener?.();
            for (const [name, service] of Object.entries(this.services)) {
                try {
                    /** @type {any} */ (service)?.destroy?.();
                } catch (error) {
                    console.error(`[env] service "${name}" destroy() failed:`, error);
                }
            }
        },
    });
}

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

serviceRegistry.addEventListener("UPDATE", (ev) => {
    if (!odoo.debug) {
        return;
    }
    const { operation, key, value } = /** @type {any} */ (ev).detail;
    if (operation !== "add" || !value?.dependencies?.length) {
        return;
    }
    Promise.resolve().then(() => {
        const missing = value.dependencies.filter(
            (/** @type {string} */ dep) => !serviceRegistry.contains(dep),
        );
        if (missing.length) {
            console.warn(
                `[registry] Service "${key}" declares missing ` +
                    `dependencies at registration time: ` +
                    `${missing.join(", ")}. ` +
                    `If a later module registers these deps, env.js will ` +
                    `start the service normally at startServices time.  ` +
                    `If a dep name is a typo or the providing module is ` +
                    `never loaded, the service will be silently skipped ` +
                    `(see the cascade-skip block in _startServices).`,
            );
        }
    });
});

/**
 * Dedup state for the cascade-skip warning below: without it, a single
 * misconfigured service re-warns on every ``startServices`` call (327+
 * identical lines in a Hoot run of ``@web/core``). Keyed by
 * (sorted-skipped-set | sorted-missing-set); process-scoped, cleared via
 * ``_resetCascadeWarningCache`` for tests.
 *
 * @type {Set<string>}
 */
const _seenCascadeWarnings = new Set();

/**
 * Test-only: clear the cascade-skip warning dedup cache so a repeated
 * misconfiguration warns again. Not part of the public env API.
 */
export function _resetCascadeWarningCache() {
    _seenCascadeWarnings.clear();
}

/**
 * Start all services registered in the service registry, resolving
 * dependencies first.
 *
 * The UPDATE listener installed on the singleton registry is owned by
 * ``env``: callers that create/dispose envs (test infra) MUST call
 * ``env.disposeServiceRegistryListener()`` on cleanup, or stale listeners
 * keep re-running services against dead envs — causing expect.step()
 * pollution and false "Circular service dependency" errors between tests.
 * Production creates one env for the page lifetime, so this is a no-op
 * there.
 *
 * @param {OdooEnv} env
 * @returns {Promise<void>}
 */
export async function startServices(env) {
    log("startServices: registry size=", serviceRegistry.getEntries().length);
    await Promise.resolve();

    const onRegistryUpdate = async (ev) => {
        await Promise.resolve();
        const { operation } = ev.detail;
        if (operation === "delete") {
            return;
        }
        try {
            await _startServices(env, new Map());
        } catch (error) {
            console.error(
                "[env] service startup pass (registry UPDATE) failed:",
                error,
            );
        }
    };
    env.disposeServiceRegistryListener?.();
    serviceRegistry.addEventListener("UPDATE", onRegistryUpdate);
    env.disposeServiceRegistryListener = () => {
        serviceRegistry.removeEventListener("UPDATE", onRegistryUpdate);
    };
    await _startServices(env, new Map());
}

/**
 * Force a complete service-startup pass and resolve once every service whose
 * dependencies are met has started.
 *
 * ``loadBundle`` only *registers* a lazy bundle's services; actually
 * starting them happens asynchronously via the registry UPDATE listener. A
 * caller that lazy-loads a bundle and immediately mounts a component reading
 * one of its services in ``setup`` (``useService`` throws if not yet in
 * ``env.services``) can race that background startup — awaiting this after
 * ``loadBundle`` closes the race deterministically. Services with genuinely
 * unregistered deps are left to the cascade-skip; re-entrant calls serialize
 * via ``startServicesPromise``. Installs no listener, safe to call
 * repeatedly.
 *
 * @param {OdooEnv} env
 * @returns {Promise<void>}
 */
export async function ensureServicesStarted(env) {
    await Promise.resolve();
    await _startServices(env, new Map());
}

/**
 * Start all services in `toStart`, resolving dependencies with O(N+E)
 * dependency-counting and reverse-edge propagation. Waves: each wave starts
 * services whose deps are met, waits for results, then propagates to unlock
 * the next wave.
 *
 * @param {OdooEnv} env
 * @param {Map<string, any>} toStart
 */
async function _startServices(env, toStart) {
    if (env._startServicesPromise) {
        return env._startServicesPromise
            .catch(() => {})
            .then(() => _startServices(env, toStart));
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

    const resolver = createWaveResolver({
        isLoaded: (dep) => dep in services,
    });

    /**
     * Register a service for dependency tracking.
     * Idempotent — skips services already tracked.
     * @param {string} name
     */
    function _trackService(name) {
        const service = toStart.get(name);
        if (!service) {
            return;
        }
        resolver.track(name, service.dependencies || []);
    }

    for (const name of toStart.keys()) {
        _trackService(name);
    }

    let _wave = 0;
    async function start() {
        for (const name of toStart.keys()) {
            _trackService(name);
        }

        const proms = [];
        const waveStarted = [];
        while (resolver.hasReady()) {
            const name = /** @type {string} */ (resolver.shift());
            if (name in services) {
                continue;
            }
            const service = toStart.get(name);
            if (!service) {
                continue;
            }
            toStart.delete(name);
            resolver.untrack(name);
            const entries = (service.dependencies || []).map((dep) => [
                dep,
                services[dep],
            ]);
            const dependencies = Object.fromEntries(entries);
            let value;
            try {
                value = service.start(env, dependencies);
            } catch (error) {
                console.error(`[env] service "${name}" failed to start (sync):`, error);
                continue;
            }
            if ("async" in service) {
                SERVICES_METADATA[name] = service.async;
            }
            waveStarted.push(name);
            proms.push(
                Promise.resolve(value).then(
                    (val) => {
                        services[name] = val ?? null;
                        resolver.propagate(name);
                    },
                    (error) => {
                        console.error(
                            `[env] service "${name}" failed to start (async):`,
                            error,
                        );
                    },
                ),
            );
        }
        if (waveStarted.length) {
            log(
                `services wave ${++_wave} started (${waveStarted.length}):`,
                waveStarted,
            );
        }
        await Promise.all(proms);
        if (proms.length) {
            return start();
        }
    }
    env._startServicesPromise = start().finally(() => {
        env._startServicesPromise = null;
    });
    await env._startServicesPromise;
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
            const skipped = [];
            let changed = true;
            while (changed) {
                changed = false;
                for (const [name, service] of toStart) {
                    const hasMissingDep = (service.dependencies || []).some(
                        (dep) => !(dep in services) && !toStart.has(dep),
                    );
                    if (hasMissingDep) {
                        toStart.delete(name);
                        skipped.push(name);
                        changed = true;
                    }
                }
            }
            if (skipped.length) {
                const dedupKey =
                    [...skipped].sort().join(",") +
                    "|" +
                    [...missingDeps].sort().join(",");
                if (!_seenCascadeWarnings.has(dedupKey)) {
                    _seenCascadeWarnings.add(dedupKey);
                    console.warn(
                        `[env] Skipped ${skipped.length} service(s) with ` +
                            `unreachable dependencies: ${skipped.join(", ")}. ` +
                            `Missing: ${[...missingDeps].sort().join(", ")}. ` +
                            `(Fires for any lazy-loaded bundle — test OR ` +
                            `production — whose provider has not been ` +
                            `evaluated yet. If the provider arrives later the ` +
                            `next startServices pass recovers it; if it never ` +
                            `arrives, consumers see env.services.<name> === ` +
                            `undefined at the use site. Callers that ` +
                            `lazy-load a production bundle and read its ` +
                            `services synchronously should await ` +
                            `ensureServicesStarted(env) after loadBundle. ` +
                            `Deduped per (skipped, missing) combination; ` +
                            `identical skips stay silent.)`,
                    );
                }
            }
        }
        if (toStart.size) {
            const depGraph = new Map();
            for (const [name, service] of toStart) {
                depGraph.set(name, service.dependencies || []);
            }
            const cycle = findDependencyCycle(depGraph);
            if (cycle) {
                throw new Error(
                    `Circular service dependency detected: ${cycle.join(" \u2192 ")}`,
                );
            }
            console.warn(
                `[env] ${toStart.size} service(s) left unstarted with no ` +
                    `dependency cycle: ${[...toStart.keys()].join(", ")}. ` +
                    `A registry update raced this startup pass; the next ` +
                    `startServices/ensureServicesStarted pass will start them.`,
            );
        }
    }
    log(
        "startServices: done — started=",
        Object.keys(services).length,
        "waves=",
        _wave,
    );
    env.bus.trigger(AppEvent.SERVICES_LOADED);
}

export const customDirectives = {
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
    log(
        "mountComponent:",
        component.name || "anon",
        "isRoot=",
        isRoot,
        "target=",
        target.tagName || target,
    );
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
