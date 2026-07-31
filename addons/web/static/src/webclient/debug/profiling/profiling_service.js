// @ts-check
/** @odoo-module native */

/** @module @web/webclient/debug/profiling/profiling_service */

import { EventBus, reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

import { ProfilingItem } from "./profiling_item.js";
import { profilingSystrayItem } from "./profiling_systray_item.js";

const systrayRegistry = registry.category("systray");

export const profilingService = {
    dependencies: ["action", "orm", "lazy_session"],
    start(env, { action, orm, lazy_session }) {
        if (!env.debug) {
            return;
        }

        const bus = new EventBus();

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

        let stateGeneration = 0;

        /**
         * @param {string} sessionKey
         * @param {string} stateKey
         */
        async function loadLazyState(sessionKey, stateKey) {
            const bootGeneration = stateGeneration;
            for (let attempt = 0; attempt < 2; attempt++) {
                try {
                    const value = await lazy_session.getValue(sessionKey);
                    if (value && stateGeneration === bootGeneration) {
                        state[stateKey] = value;
                    }
                    return;
                } catch {}
            }
        }
        loadLazyState("profile_session", "session");
        loadLazyState("profile_collectors", "collectors");
        loadLazyState("profile_params", "params");

        notify();

        async function setProfiling(params) {
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
                Promise.resolve(action.doAction(resp)).catch(console.warn);
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
