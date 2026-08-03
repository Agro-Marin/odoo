// @ts-check
/** @odoo-module native */

/** @module @web/env */

import { App, EventBus } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { reportJsError } from "@web/core/errors/error_beacon";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/translation";
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
 * @type {Set<string>}
 */
const _seenCascadeWarnings = new Set();

export function _resetCascadeWarningCache() {
    _seenCascadeWarnings.clear();
}

/**
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
 * @param {OdooEnv} env
 * @returns {Promise<void>}
 */
export async function ensureServicesStarted(env) {
    await Promise.resolve();
    await _startServices(env, new Map());
}

/**
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
    /**
     * Beacon a service that never started.
     *
     * Both call sites below deliberately swallow the failure — the app boots
     * without the service and its dependents are skipped — so nothing else
     * reaches the window's error hooks and the server never hears about it.
     * That silence is what this repairs: a whole class of client failure was
     * only ever visible to someone with the console open.
     *
     * The failing ``error`` is passed as the ``cause`` rather than
     * ``error.cause``: the message already says which service died, and what a
     * reader needs next is why — ``TypeError: Cannot read properties of
     * undefined (reading 'subscribe')`` — plus that error's own chain. Passing
     * ``error.cause`` would skip exactly that line, which is usually the
     * whole diagnosis.
     *
     * Reporting only the failing service, never the dependents that get
     * skipped afterwards: one base service can strand dozens, and they are all
     * consequences of the same fact.
     *
     * @param {string} name service that failed
     * @param {"sync" | "async"} mode which arm of the start caught it
     * @param {unknown} error whatever ``start()`` threw or rejected with
     */
    function _reportServiceFailure(name, mode, error) {
        reportJsError({
            kind: "service_start",
            message: `service "${name}" failed to start (${mode})`,
            stack: /** @type {any} */ (error)?.stack
                ? String(/** @type {any} */ (error).stack)
                : "",
            cause: error,
        });
    }

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
                _reportServiceFailure(name, "sync", error);
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
                        _reportServiceFailure(name, "async", error);
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
    /**
     * @param {MouseEvent} ev
     * @param {Function} value
     * @param {boolean} hasStop
     * @param {boolean} hasPrevent
     */
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
 * @param {import("@odoo/owl").Component} component
 * @param {HTMLElement} target
 * @param {Partial<ConstructorParameters<typeof App>[1]>} [appConfig]
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
