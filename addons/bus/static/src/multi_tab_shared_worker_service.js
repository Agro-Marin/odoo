/** @odoo-module native */
import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { Deferred } from "@web/core/utils/concurrency";
const STATE = Object.freeze({
    INIT: "INIT",
    MASTER: "MASTER",
    REGISTERED: "REGISTERED",
    UNREGISTERED: "UNREGISTERED",
});

export const multiTabSharedWorkerService = {
    dependencies: ["worker_service"],
    start(env, { worker_service: workerService }) {
        const bus = new EventBus();
        let responseDeferred = null;
        let state = STATE.INIT;
        // Memoizes the in-flight worker start so concurrent `isOnMainTab()`
        // callers (common at boot) don't each run `startWorker` — which would
        // send a duplicate `ELECTION:REGISTER`.
        let startPromise = null;
        browser.addEventListener("pagehide", unregister);
        browser.addEventListener("pageshow", (ev) => {
            if (ev.persisted && state === STATE.UNREGISTERED) {
                // Page restored from bfcache: `pagehide` unregistered us but
                // the worker (and its port) is still alive. Re-join the
                // election so main-tab tracking resumes instead of reporting
                // `false` forever.
                workerService.send("ELECTION:REGISTER");
                state = STATE.REGISTERED;
            }
        });

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

        function startWorker() {
            return (startPromise ??= (async () => {
                await workerService.ensureWorkerStarted();
                await workerService.registerHandler(messageHandler);
                workerService.send("ELECTION:REGISTER");
                state = STATE.REGISTERED;
            })());
        }

        function unregister() {
            workerService.send("ELECTION:UNREGISTER");
            state = STATE.UNREGISTERED;
        }

        return {
            bus,
            isOnMainTab: async () => {
                if (state === STATE.UNREGISTERED) {
                    return false;
                }
                if (state === STATE.INIT) {
                    await startWorker();
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
