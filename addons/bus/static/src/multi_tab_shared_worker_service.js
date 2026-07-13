/** @odoo-module native */
import { WORKER_STATE } from "@bus/services/worker_service";
import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { Deferred } from "@web/core/utils/concurrency";

const STATE = Object.freeze({
    INIT: "INIT",
    MASTER: "MASTER",
    REGISTERED: "REGISTERED",
    UNREGISTERED: "UNREGISTERED",
});

/**
 * SharedWorker-based main-tab election strategy. Normally instantiated by the
 * `multi_tab` facade (multi_tab_service.js) AFTER worker_service settled on an
 * effectively shared worker; it still guards against a FAILED worker service
 * for direct (test) usage.
 */
export const multiTabSharedWorkerService = {
    dependencies: ["worker_service"],
    start(env, { worker_service: workerService }) {
        const bus = new EventBus();
        let responseDeferred = null;
        let state = STATE.INIT;
        // Memoizes the in-flight worker start so concurrent `isOnMainTab()`
        // callers (common at boot) don't each run the init sequence — which
        // would register the message handler several times.
        let startPromise = null;
        // Degraded mode: the worker service ended FAILED (send/registerHandler
        // are no-ops), so no election traffic can ever flow. `isOnMainTab()`
        // then resolves `false` immediately: this tab takes no main-tab
        // duties. The `multi_tab` facade normally prevents this case by
        // selecting the localStorage election instead.
        let failed = false;
        // TERMINAL unregistration (public `unregister()`, e.g. bus_service on
        // BUS:OUTDATED keeping stale-code tabs out of main-tab duties), as
        // opposed to the TRANSIENT one of `pagehide`: a terminated tab must
        // never re-register itself on `pageshow`.
        let terminated = false;

        function messageHandler(messageEv) {
            const { type, data } = messageEv.data;
            if (!type?.startsWith("ELECTION:")) {
                return;
            }
            switch (type) {
                case "ELECTION:IS_MASTER_RESPONSE":
                    responseDeferred?.resolve(data.answer);
                    responseDeferred = null;
                    break;
                case "ELECTION:HEARTBEAT_REQUEST":
                    // Never reply while unregistered: a heartbeat from a gone
                    // tab keeps the worker's `lastHeartbeat` fresh (blocking
                    // re-election) and, during an election, could crown this
                    // tab master while it denies mastership client-side.
                    if (state !== STATE.UNREGISTERED) {
                        workerService.send("ELECTION:HEARTBEAT");
                    }
                    break;
                case "ELECTION:ASSIGN_MASTER":
                    // Ignore a stray/in-flight assignment for a tab that has
                    // already unregistered (mirrors the UNASSIGN_MASTER guard):
                    // a gone tab must not resurrect itself as main.
                    if (state !== STATE.UNREGISTERED) {
                        state = STATE.MASTER;
                        bus.trigger("become_main_tab");
                    }
                    break;
                case "ELECTION:UNASSIGN_MASTER":
                    if (state !== STATE.UNREGISTERED) {
                        state = STATE.REGISTERED;
                    }
                    bus.trigger("no_longer_main_tab");
                    break;
                default:
                    console.warn(
                        "multiTabSharedWorkerService received unknown message type:",
                        type,
                    );
            }
        }

        /**
         * Idempotent registration entry point: performs the one-time worker
         * init/handler setup, then (re-)joins the election if this tab is not
         * currently registered. Used both by the first `isOnMainTab()` call
         * and by the bfcache `pageshow` re-registration, so BOTH go through
         * the INIT gate — a raw `send("ELECTION:REGISTER")` without the
         * handler registered would leave the tab registered-but-deaf,
         * hanging every `isOnMainTab()` caller.
         */
        async function ensureRegistered() {
            startPromise ??= (async () => {
                await workerService.ensureWorkerStarted();
                if (workerService.state === WORKER_STATE.FAILED) {
                    failed = true;
                    return;
                }
                await workerService.registerHandler(messageHandler);
            })();
            await startPromise;
            if (failed || terminated) {
                return;
            }
            if (state === STATE.INIT || state === STATE.UNREGISTERED) {
                workerService.send("ELECTION:REGISTER");
                state = STATE.REGISTERED;
            }
        }

        /** Leave the election without giving up the right to come back. */
        function unregisterTransiently() {
            workerService.send("ELECTION:UNREGISTER");
            state = STATE.UNREGISTERED;
        }

        function unregister() {
            terminated = true;
            unregisterTransiently();
        }

        browser.addEventListener("pagehide", unregisterTransiently);
        browser.addEventListener("pageshow", (ev) => {
            if (ev.persisted && !terminated && startPromise) {
                // Page restored from bfcache: `pagehide` unregistered us but
                // the worker (and its port) is still alive. Re-join the
                // election so main-tab tracking resumes instead of reporting
                // `false` forever. Only tabs that had actually registered
                // (`startPromise` set) re-join; terminated (outdated) tabs
                // never do.
                ensureRegistered();
            }
        });

        return {
            bus,
            isOnMainTab: async () => {
                if (state === STATE.UNREGISTERED) {
                    return false;
                }
                if (state === STATE.INIT) {
                    await ensureRegistered();
                }
                if (failed || state === STATE.UNREGISTERED) {
                    return false;
                }
                if (!responseDeferred) {
                    responseDeferred = new Deferred();
                    workerService.send("ELECTION:IS_MASTER?");
                }
                return responseDeferred;
            },
            unregister,
        };
    },
};
