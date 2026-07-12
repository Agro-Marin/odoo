// @ts-check
/** @odoo-module native */

/** @module @web/webclient/debug/profiling/profiling_service - Service managing Python profiling session state, collector toggles, and systray indicator */

import { EventBus, reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

import { ProfilingItem } from "./profiling_item.js";
import { profilingSystrayItem } from "./profiling_systray_item.js";

const systrayRegistry = registry.category("systray");

/**
 * Profile state (``profile_session``, ``profile_collectors``, ``profile_params``)
 * is fetched lazily via the ``lazy_session`` service after ``WEB_CLIENT_READY``;
 * until then the service runs with defaults — acceptable since profiling is
 * debug-only and the systray indicator just appears a moment after boot.
 */
export const profilingService = {
    dependencies: ["orm", "lazy_session"],
    start(env, { orm, lazy_session }) {
        if (!env.debug) {
            return;
        }

        function notify() {
            if (
                systrayRegistry.contains("web.profiling") &&
                state.isEnabled === false
            ) {
                systrayRegistry.remove("web.profiling");
            }
            if (
                !systrayRegistry.contains("web.profiling") &&
                state.isEnabled === true
            ) {
                systrayRegistry.add("web.profiling", profilingSystrayItem, {
                    sequence: 99,
                });
            }
            bus.trigger("UPDATE");
        }

        const state = reactive(
            {
                session: false,
                collectors: ["sql", "traces_async"],
                params: {},
                get isEnabled() {
                    return Boolean(state.session);
                },
            },
            notify,
        );

        // Monotonic generation bumped on every user-driven state change
        // (setProfiling). Lazy-session values captured at boot are only applied
        // if the generation is unchanged: a slow lazy fetch must never overwrite
        // a fresh toggle the user made in the meantime (e.g. a late
        // ``profile_session`` string clobbering a just-turned-off ``false``).
        let stateGeneration = 0;

        /**
         * Apply a boot-time lazy-session value into ``state[stateKey]`` unless
         * the user changed state since the fetch started. Retries the fetch
         * once on transient failure so a single hiccup can't strand profiling
         * on defaults for the whole page.
         *
         * @param {string} sessionKey lazy_session key
         * @param {string} stateKey reactive state slot
         */
        async function loadLazyState(sessionKey, stateKey) {
            const bootGeneration = stateGeneration;
            for (let attempt = 0; attempt < 2; attempt++) {
                try {
                    const value = await lazy_session.getValue(sessionKey);
                    if (value && stateGeneration === bootGeneration) {
                        // Assign through the reactive proxy so ``notify`` re-runs
                        // and the systray updates for a session active on load.
                        state[stateKey] = value;
                    }
                    return;
                } catch {
                    // Transient failure: retry once, then give up (keep default).
                }
            }
        }
        // Populate from the lazy session once it arrives.
        loadLazyState("profile_session", "session");
        loadLazyState("profile_collectors", "collectors");
        loadLazyState("profile_params", "params");

        const bus = new EventBus();
        notify();

        async function setProfiling(params) {
            // User-driven change: bump the generation so any still-in-flight
            // boot-time lazy value is discarded instead of overwriting this.
            stateGeneration++;
            const kwargs = Object.assign(
                {
                    collectors: state.collectors,
                    params: state.params,
                    profile: state.isEnabled,
                },
                params,
            );
            const resp = await orm.call("ir.profile", "set_profiling", [], kwargs);
            if (resp.type) {
                // most likely an "ir.actions.act_window"
                env.services.action.doAction(resp);
            } else {
                state.session = resp.session;
                state.collectors = resp.collectors;
                state.params = resp.params;
            }
        }

        function profilingItem() {
            return {
                type: "component",
                Component: ProfilingItem,
                props: { bus },
                sequence: 570,
                section: "tools",
            };
        }

        registry
            .category("debug")
            .category("default")
            .add("profilingItem", /** @type {any} */ (profilingItem));

        return {
            state,
            async toggleProfiling() {
                await setProfiling({ profile: !state.isEnabled });
            },
            async toggleCollector(collector) {
                const nextCollectors = state.collectors.slice();
                const index = nextCollectors.indexOf(collector);
                if (index >= 0) {
                    nextCollectors.splice(index, 1);
                } else {
                    nextCollectors.push(collector);
                }
                await setProfiling({ collectors: nextCollectors });
            },
            async setParam(key, value) {
                const nextParams = { ...state.params };
                nextParams[key] = value;
                await setProfiling({ params: nextParams });
            },
            isCollectorEnabled(collector) {
                return state.collectors.includes(collector);
            },
        };
    },
};

registry.category("services").add("profiling", profilingService);
