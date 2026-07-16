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

// Types

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

// makeEnv

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

// Service Launcher

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

// Debug-mode early-detection of missing service dependencies: catches typos
// at registration time instead of waiting for the cascade-skip in
// ``_startServices``. Silent in production (third-party addons may register
// deps that load later). Defers one microtask so sibling sync registrations
// land before we declare a dep missing.
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

// Startup-pass serialization is stored PER-ENV (``env._startServicesPromise``),
// not in a module global: independent envs (test suites, embedded sub-apps)
// must not serialize behind one another, and a rejection in one env's pass must
// not cross-contaminate another env's. Within a single env, concurrent
// ``_startServices`` passes still serialize via that env's own slot.

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
    // Wait for all synchronous code so that if new services that depend on
    // one another are added to the registry, they're all present before we
    // start them regardless of the order they're added to the registry.
    await Promise.resolve();

    const onRegistryUpdate = async (ev) => {
        // Wait for all synchronous code so that if new services that depend on
        // one another are added to the registry, they're all present before we
        // start them regardless of the order they're added to the registry.
        await Promise.resolve();
        const { operation } = ev.detail;
        if (operation === "delete") {
            // We hardly see why it would be useful to remove a service.
            // Furthermore we could encounter problems with dependencies.
            // Keep it simple!
            return;
        }
        // Always schedule a FRESH pass with its own Map: ``_startServices``
        // repopulates it from the registry (every registered service not yet
        // in ``env.services``), and serializes behind any in-flight pass via
        // ``startServicesPromise``. Sharing a Map with an in-flight pass
        // could inject an already-startable service into ``toStart`` in the
        // microtask window between the pass's last wave settling and its
        // post-await checks — a leftover the old code misreported as a
        // circular dependency.
        try {
            await _startServices(env, new Map());
        } catch (error) {
            // This runs as an event-listener callback: a rejection here is
            // awaited by nobody and would surface only as a context-free
            // unhandled rejection. Log which async startup pass failed so a
            // late-registered service that throws on start is diagnosable.
            console.error(
                "[env] service startup pass (registry UPDATE) failed:",
                error,
            );
        }
    };
    // If startServices is called more than once on the same env (test patterns
    // that re-run startup after an expected throw, for instance), drop the
    // listener installed by the previous call before installing a new one —
    // otherwise both stay attached and double-fire on every UPDATE.
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
    // Let any pending synchronous registrations land first, matching the
    // microtask convention used by startServices / onRegistryUpdate.
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
        // Serialize behind the in-flight pass FOR THIS ENV, but run this
        // independent pass regardless of that pass's outcome. A rejecting
        // service.start() in the earlier pass (propagated through the
        // `start().finally(...)` below, which does not catch) must not cancel
        // this caller's pass nor surface as this caller's unrelated rejection.
        // `.catch(() => {})` swallows only the *previous* pass's result — the
        // original caller of that pass still sees its own rejection via its own
        // `await`, and this pass's own errors still propagate normally.
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

    // O(N+E) dependency resolution — shared impl in
    // ``@web/core/utils/dependency_graph`` (pending-count/reverse-edge
    // bookkeeping); this file drives waves and calls service.start().
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

    // Initial tracking
    for (const name of toStart.keys()) {
        _trackService(name);
    }

    // Start services in waves: ready services run in parallel, then
    // propagate to unlock dependents.
    let _wave = 0;
    async function start() {
        // Track any new services added via registry UPDATE listener
        for (const name of toStart.keys()) {
            _trackService(name);
        }

        const proms = [];
        const waveStarted = [];
        while (resolver.hasReady()) {
            // `hasReady()` guarantees `shift()` returns a value here.
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
                // A single throwing service.start() must NOT abort the whole
                // boot wave. Left unguarded it rejects Promise.all(proms) →
                // rejects startServicesPromise → fails mountComponent → the
                // boot-failure overlay blanks the ENTIRE app (100+ services, one
                // broken third-party service takes down everything). Log with the
                // service name and skip it: the service was already removed from
                // ``toStart`` and untracked above and its result is never stored,
                // so the post-wave cascade-skip sees it as absent from both
                // ``services`` and ``toStart`` and drops its dependents — they
                // then fail at their own use site, the same contract as an
                // unreachable dependency.
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
                        // Use ?? (not ||): a service resolving to a falsy-but-valid
                        // value (0, "", false) must be preserved; only null/undefined
                        // collapse to null.
                        services[name] = val ?? null;
                        resolver.propagate(name);
                    },
                    (error) => {
                        // Same rationale as the sync catch above: a rejected
                        // service promise must not reject the wave. Skip it (no
                        // propagate, so dependents stay pending and cascade-skip
                        // after the wave); the app degrades at the use site
                        // instead of failing globally.
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
            // Cascade-skip services whose deps aren't in the registry. A dep
            // can legitimately be absent because of a lazy-loaded TEST bundle
            // (provider never imported) or a lazy-loaded PRODUCTION bundle
            // (e.g. ``spreadsheet.o_spreadsheet``) where ESM import order lets
            // a consumer register before its provider — self-healing on the
            // next registry UPDATE. A caller that lazy-loads such a bundle
            // and synchronously reads one of its services in ``setup`` must
            // await ``ensureServicesStarted(env)`` after ``loadBundle`` —
            // see ``addSpreadsheetActionLazyLoader``.
            //
            // Skipping (not throwing) is correct: a dep that never arrives
            // just leaves its consumer unstarted (fails at the use site, not
            // globally); a dep that arrives later is recovered by the next
            // startServices/ensureServicesStarted pass; genuine circular
            // deps still throw below since the cascade only removes services
            // with truly missing deps.
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
                // Dedup by (skipped-set, missing-set) so a misconfiguration
                // repeated across tests only warns once (see
                // `_seenCascadeWarnings` declaration above).
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
            // After the cascade-skip (and wave-resolver fixpoint earlier),
            // anything still pending has all its deps registered but the
            // resolver couldn't progress on it — normally a circular
            // dependency, which remains a hard error (genuine programming
            // bug). Only throw when a cycle is actually FOUND: leftovers
            // without one mean a startable service slipped in after the wave
            // loop finished (a registry UPDATE racing the post-await checks)
            // — the same documented lazy-bundle state as the cascade-skip;
            // the next startServices/ensureServicesStarted pass recovers it.
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
    // t-custom-click="handler": adds "click"/"auxclick" listeners that call
    // the global "click" handler with (ev, isMiddleClick). "stop"/"prevent"
    // modifiers are resolved at compile time into boolean flags, avoiding
    // runtime JSON.parse + array iteration on every click.
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
