// @ts-check
/** @odoo-module native */

/** @module @web/env - OWL environment factory, service dependency resolution, and app mounting */

import { App, EventBus } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { AppEvent } from "@web/core/events";
import { appTranslateFn } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { createWaveResolver, findDependencyCycle } from "@web/core/utils/dependency_graph";
import { SERVICES_METADATA } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { makeAssetLog } from "@web/core/utils/asset_log";

const log = makeAssetLog("env");

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

// Debug-mode early-detection of missing service dependencies.
//
// Catches typos at ``registry.add()`` time for synchronously-loaded
// services: instead of waiting until ``startServices`` runs and the
// cascade-skip silently drops a misconfigured service, the developer
// sees a warning at the point of registration.  Lazy-loaded services
// (registered after the first microtask) are still handled by the
// cascade-skip in ``_startServices`` — this validator just adds a
// faster signal for the common case where the typo is in a file the
// debug-mode developer just edited.
//
// Production stays silent: the cascade-skip is the source of truth
// for runtime behavior, and third-party addons may legitimately
// declare deps that load later in production bundles.  Generating a
// console.warn for every such case in user environments would only
// add noise.
//
// The listener defers one microtask before checking, matching the
// convention used by ``_startServices`` at line ~99
// (``await Promise.resolve()``) so that sibling synchronous
// registrations have a chance to land before we declare a dep
// missing.
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

let startServicesPromise = null;

/**
 * Module-scope dedup state for the cascade-skip warning emitted by
 * ``_startServices``.  Each test in a Hoot run typically calls
 * ``startServices`` once via ``makeMockEnv`` / ``mountComponent``, so a
 * single misconfigured service (e.g. ``spreadsheet_dashboard_loader``
 * registering without ``geo_json_service``) would trigger one warning
 * per test — 327+ identical lines in the ``@web/core`` suite.
 *
 * Keying by ``(sorted-skipped-set | sorted-missing-set)`` collapses
 * those identical warnings to one per unique combination.  Different
 * shapes (a new service joins the skipped set, a different missing dep
 * appears) get their own warning, so genuinely new misconfigurations
 * still surface.
 *
 * The Set is process-scoped; tests that need to re-observe the warning
 * (e.g. unit tests for this very dedup behaviour) clear it via the
 * exported ``_resetCascadeWarningCache`` helper.
 *
 * @type {Set<string>}
 */
const _seenCascadeWarnings = new Set();

/**
 * Test-only escape hatch: clear the cascade-skip warning dedup cache so
 * a subsequent ``startServices`` with the same misconfiguration warns
 * again.  Not part of the public env API — production code never needs
 * it (the same misconfiguration repeating is exactly what dedup is for).
 */
export function _resetCascadeWarningCache() {
    _seenCascadeWarnings.clear();
}

/**
 * Start all services registered in the service registry, while making sure
 * each service dependencies are properly fulfilled.
 *
 * The UPDATE listener installed on the singleton service registry to handle
 * late-arriving services (lazy-loaded bundles registering services after
 * startup) is owned by ``env``: callers that create and dispose envs (test
 * infrastructure) MUST invoke ``env.disposeServiceRegistryListener()`` on
 * cleanup. Without it, every prior env's listener stays attached to the
 * shared registry and re-fires on every future ``serviceRegistry.add``,
 * re-running services against stale envs — observable as expect.step()
 * pollution between tests and false "Circular service dependency" errors.
 *
 * Production code creates exactly one env that lives for the page lifetime,
 * so the cleanup hook is a no-op there.
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

    const toStart = new Map();
    const onRegistryUpdate = async (ev) => {
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

    // O(N+E) dependency resolution — shared implementation in
    // ``@web/core/utils/dependency_graph``.  The resolver does the
    // pending-count / reverse-edge bookkeeping; this file drives it
    // and does the actual service.start() work each wave.
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

    // Start services in waves: each wave starts all ready services in
    // parallel, waits for their results, then propagates to dependents.
    let _wave = 0;
    async function start() {
        // Track any new services added via registry UPDATE listener
        for (const name of toStart.keys()) {
            _trackService(name);
        }

        const proms = [];
        const waveStarted = [];
        while (resolver.hasReady()) {
            const name = resolver.shift();
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
            const value = service.start(env, dependencies);
            if ("async" in service) {
                SERVICES_METADATA[name] = service.async;
            }
            waveStarted.push(name);
            proms.push(
                Promise.resolve(value).then((val) => {
                    services[name] = val || null;
                    resolver.propagate(name);
                }),
            );
        }
        if (waveStarted.length) {
            log(`services wave ${++_wave} started (${waveStarted.length}):`, waveStarted);
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
            // Cascade-skip services whose declared dependencies cannot be
            // met.  In production (``web.assets_web``) every JS file in
            // the bundle is eagerly evaluated by esbuild at load time, so
            // every service that registers itself does so alongside its
            // declared deps — the missing-dep case is structurally
            // impossible.  The only scenario where a service can be
            // registered without its provider is the lazy-loaded test
            // bundle (``web.assets_unit_tests``, listed in
            // ``AssetsBundle.IMPORT_MAP_INCLUDES``): a test file's static
            // ``import`` registers its consumer service, but if no other
            // file in the running test set transitively imports the
            // provider, the provider's ``registry.add(...)`` never
            // executes.
            //
            // Pre-2026-05-22 this branch threw, cascade-failing every
            // test in the run (a single offending test file would knock
            // out the entire ``@web/core`` suite — see the
            // ``spreadsheet_dashboard_loader`` <- ``geo_json_service``
            // historical incident).  The corrective workaround at
            // ``tests/_framework/module_set.hoot.js`` ran a service-
            // cascade-removal pass at framework init, but it ran BEFORE
            // test files lazy-loaded, so newly-registered services
            // slipped through.
            //
            // Skipping with a warning is the correct behavior because:
            //   1. Production cannot reach this branch (esbuild eager
            //      bundle).
            //   2. In test mode, consumers of the skipped service that
            //      actually need it will fail with a precise
            //      "cannot read property of undefined" pointing at the
            //      specific use site, which is more debuggable than a
            //      global startup error.
            //   3. Genuine circular dependencies still throw below — the
            //      cascade only removes services with truly missing deps,
            //      so leftover entries are guaranteed cyclical.
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
                // Dedup by (skipped-set, missing-set) so the same
                // misconfiguration repeated across tests only warns once.
                // See `_seenCascadeWarnings` declaration above for the
                // rationale (avoids 327+ identical warnings in @web/core).
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
                            `(Production bundles eagerly evaluate every file, ` +
                            `so this branch only fires in lazy-loaded test ` +
                            `bundles.  Components or tests that consume any of ` +
                            `these services will see env.services.<name> === ` +
                            `undefined at the use site.  This message dedupes ` +
                            `per (skipped, missing) combination; subsequent ` +
                            `identical skips stay silent.)`,
                    );
                }
            }
        }
        if (toStart.size) {
            // After the cascade-skip (and after the wave-resolver has
            // run to fixpoint earlier), anything still pending has all
            // its declared deps registered: the resolver couldn't make
            // progress on it, so it must be part of a circular
            // dependency.  This remains a hard error in all environments
            // (genuine programming bug).
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
    }
    log("startServices: done — started=", Object.keys(services).length, "waves=", _wave);
    env.bus.trigger(AppEvent.SERVICES_LOADED);
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
    log("mountComponent:", component.name || "anon", "isRoot=", isRoot,
        "target=", target.tagName || target);
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
