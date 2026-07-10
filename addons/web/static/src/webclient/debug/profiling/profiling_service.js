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

        // Populate from the lazy session once it arrives.  Each assignment goes
        // through the reactive proxy so ``notify`` re-runs and the systray
        // updates when a profiling session was active on page load.
        lazy_session.getValue("profile_session", (value) => {
            if (value) {
                state.session = value;
            }
        });
        lazy_session.getValue("profile_collectors", (value) => {
            if (value) {
                state.collectors = value;
            }
        });
        lazy_session.getValue("profile_params", (value) => {
            if (value) {
                state.params = value;
            }
        });

        const bus = new EventBus();
        notify();

        async function setProfiling(params) {
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
