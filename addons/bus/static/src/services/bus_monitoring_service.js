/** @odoo-module native */
import { WORKER_STATE } from "@bus/services/worker_service";
import { CONNECTION_STATE } from "@bus/workers/websocket_worker_constants";
import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
/**
 * Detect lost connections to the bus. A connection is considered as lost if it
 * couldn't be established after a reconnect attempt.
 */
export class BusMonitoringService {
    isConnectionLost = false;
    isReconnecting = false;

    constructor(env, services) {
        const reactiveThis = reactive(this);
        reactiveThis.setup(env, services);
        return reactiveThis;
    }

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {Partial<import("services").Services>} services
     */
    setup(env, { bus_service, worker_service }) {
        bus_service.addEventListener("BUS:WORKER_STATE_UPDATED", ({ detail }) =>
            this.workerStateOnChange(detail),
        );
        browser.addEventListener("offline", () => (this.isReconnecting = false));
        // A worker service that ends FAILED never emits any
        // BUS:WORKER_STATE_UPDATED: without this check the connection would
        // read as healthy forever on a permanently dead bus (mail's
        // connection-lost banner would never show). Chained on the deferred —
        // not `ensureWorkerStarted()` — so monitoring never boots the worker
        // itself.
        worker_service.connectionInitializedDeferred.then(() => {
            if (worker_service.state === WORKER_STATE.FAILED) {
                this.isConnectionLost = true;
                this.isReconnecting = false;
            }
        });
    }

    /**
     * Handle connection-state changes of the WebSocket worker.
     *
     * @param {CONNECTION_STATE[keyof CONNECTION_STATE]} state
     */
    workerStateOnChange(state) {
        switch (state) {
            case CONNECTION_STATE.CONNECTING: {
                this.isReconnecting = true;
                break;
            }
            case CONNECTION_STATE.CONNECTED: {
                this.isReconnecting = false;
                this.isConnectionLost = false;
                break;
            }
            case CONNECTION_STATE.DISCONNECTED: {
                if (this.isReconnecting) {
                    this.isConnectionLost = true;
                    this.isReconnecting = false;
                }
                break;
            }
        }
    }
}

export const busMonitoringservice = {
    dependencies: ["bus_service", "worker_service"],
    start(env, services) {
        return new BusMonitoringService(env, services);
    },
};

registry.category("services").add("bus.monitoring_service", busMonitoringservice);
