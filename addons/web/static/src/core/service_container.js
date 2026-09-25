// @ts-check
/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { reportJsError } from "@web/core/errors/error_beacon";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { makeAssetLog, serviceLog } from "@web/core/utils/asset_log";
import { deferUntilBundlesSettled } from "@web/core/utils/bundle_transaction";
import {
    createWaveResolver,
    findDependencyCycle,
} from "@web/core/utils/dependency_graph";
import { SERVICES_METADATA } from "@web/core/utils/hooks";

const log = makeAssetLog("env");
const debugLog = makeLogger("web.env");

/**
 * @typedef {{
 * bus: import("@odoo/owl").EventBus;
 * debug: string;
 * services: Record<string, any>;
 * readonly isSmall: boolean;
 * [key: string]: any;
 * }} ServiceContext
 */

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

/** @type {Set<string>} */
const _seenCascadeWarnings = new Set();

export function _resetCascadeWarningCache() {
    _seenCascadeWarnings.clear();
}

export class ServiceContainer {
    /** @type {Promise<void> | null} */
    _pending = null;
    /** @type {(() => void) | null} */
    _stopListening = null;

    /** @param {ServiceContext} context */
    constructor(context) {
        this.context = context;
        this.services = context.services;
    }

    async start() {
        log("startServices: registry size=", serviceRegistry.getEntries().length);
        await Promise.resolve();

        const runStartupPass = async () => {
            try {
                await this._start(new Map());
            } catch (error) {
                console.error(
                    "[env] service startup pass (registry UPDATE) failed:",
                    error,
                );
            }
        };
        /** @param {any} ev */
        const onRegistryUpdate = async (ev) => {
            await Promise.resolve();
            const { operation } = ev.detail;
            if (operation === "delete") {
                return;
            }
            if (deferUntilBundlesSettled(runStartupPass)) {
                return;
            }
            await runStartupPass();
        };
        this.stopListening();
        serviceRegistry.addEventListener("UPDATE", onRegistryUpdate);
        this._stopListening = () => {
            serviceRegistry.removeEventListener("UPDATE", onRegistryUpdate);
        };
        await this._start(new Map());
    }

    async startMissing() {
        await Promise.resolve();
        await this._start(new Map());
    }

    stopListening() {
        this._stopListening?.();
        this._stopListening = null;
    }

    destroy() {
        this.stopListening();
        for (const [name, service] of Object.entries(this.services)) {
            try {
                /** @type {any} */ (service)?.destroy?.();
            } catch (error) {
                console.error(`[env] service "${name}" destroy() failed:`, error);
            }
        }
    }

    /** @param {Map<string, any>} toStart */
    async _start(toStart) {
        if (this._pending) {
            return this._pending.catch(() => {}).then(() => this._start(toStart));
        }
        const { context, services } = this;
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

        /** @param {string} name */
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
         * @param {string} name
         * @param {"sync" | "async"} mode
         * @param {unknown} error
         */
        function _reportServiceFailure(name, mode, error) {
            serviceLog("failed", name, mode);
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
                const endStart = debugLog.perf(`service ${name}`);
                try {
                    value = service.start(context, dependencies);
                } catch (error) {
                    console.error(
                        `[env] service "${name}" failed to start (sync):`,
                        error,
                    );
                    _reportServiceFailure(name, "sync", error);
                    continue;
                }
                if ("async" in service) {
                    SERVICES_METADATA[name] = service.async;
                }
                waveStarted.push(name);
                serviceLog("start", name, service.dependencies || []);
                proms.push(
                    Promise.resolve(value).then(
                        (val) => {
                            services[name] = val ?? null;
                            endStart({ dependencies: service.dependencies || [] });
                            serviceLog("started", name);
                            resolver.propagate(name);
                        },
                        (error) => {
                            console.error(
                                `[env] service "${name}" failed to start (async):`,
                                error,
                            );
                            endStart({ failed: true });
                            _reportServiceFailure(name, "async", error);
                        },
                    ),
                );
            }
            if (waveStarted.length) {
                debugLog.pipeline("services wave", () => ({
                    wave: _wave + 1,
                    started: waveStarted,
                }));
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
        this._pending = start().finally(() => {
            this._pending = null;
        });
        await this._pending;
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
                                `arrives, consumers see services.<name> === ` +
                                `undefined at the use site. Callers that ` +
                                `lazy-load a production bundle and read its ` +
                                `services synchronously should await ` +
                                `startMissingServices(env) after loadBundle. ` +
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
                        `startServices/startMissingServices pass will start them.`,
                );
            }
        }
        log(
            "startServices: done — started=",
            Object.keys(services).length,
            "waves=",
            _wave,
        );
        context.bus.trigger(AppEvent.SERVICES_LOADED);
    }
}
