/** @odoo-module native */
import { multiTabFallbackService } from "@bus/multi_tab_fallback_service";
import { multiTabSharedWorkerService } from "@bus/multi_tab_shared_worker_service";
import { EventBus } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * Facade in charge of electing the main tab, choosing the election strategy
 * at RUNTIME, once `worker_service` has settled on what it effectively runs:
 *
 * - effective SharedWorker -> worker-based election (one worker arbitrates
 *   all tabs);
 * - dedicated per-tab Worker or FAILED worker -> localStorage election.
 *
 * Import-time feature detection (`browser.SharedWorker` presence) is NOT
 * enough: SharedWorker construction can fail at runtime and worker_service
 * then falls back to a dedicated per-tab Worker. A per-tab "shared" election
 * would crown EVERY tab main (duplicate notifications/sounds); the
 * localStorage election is the correct strategy there.
 *
 * The strategy is only instantiated on the first `isOnMainTab()` call (which
 * is also what triggered the election in the previous, import-time design):
 * starting the worker just to elect a main tab nobody asked about would be
 * wasted work on worker-less pages.
 *
 * Public API (kept identical to both strategies — consumers: mail
 * out_of_focus/discuss_core_web/rtc thread patch, survey form, voip
 * user_agent, bus outdated_page_watcher/bus_service):
 * - `isOnMainTab(): Promise<boolean>`
 * - `unregister()`: terminal — the tab permanently gives up main-tab duties.
 * - `bus`: EventBus emitting "become_main_tab" / "no_longer_main_tab".
 */
export const multiTabService = {
    dependencies: ["worker_service"],
    start(env, services) {
        const { worker_service: workerService } = services;
        const bus = new EventBus();
        // Set by `unregister()`: also honoured when the strategy is not
        // instantiated yet (the strategy is then unregistered right after
        // its creation, before any election message can crown this tab).
        let terminated = false;
        /** @type {Promise<{isOnMainTab: () => Promise<boolean>, unregister: () => void}>} */
        let strategyPromise = null;

        function ensureStrategy() {
            return (strategyPromise ??= (async () => {
                await workerService.ensureWorkerStarted();
                const useSharedWorkerElection = workerService.workerKind === "shared";
                const strategy = useSharedWorkerElection
                    ? multiTabSharedWorkerService.start(env, services)
                    : multiTabFallbackService.start(env, services);
                // Relay so consumers can subscribe on the facade before (and
                // independently of) strategy instantiation.
                for (const type of ["become_main_tab", "no_longer_main_tab"]) {
                    strategy.bus.addEventListener(type, () => bus.trigger(type));
                }
                if (terminated) {
                    strategy.unregister();
                }
                return strategy;
            })());
        }

        return {
            bus,
            async isOnMainTab() {
                if (terminated) {
                    return false;
                }
                const strategy = await ensureStrategy();
                return strategy.isOnMainTab();
            },
            unregister() {
                terminated = true;
                strategyPromise?.then((strategy) => strategy.unregister());
            },
        };
    },
};

registry.category("services").add("multi_tab", multiTabService);
