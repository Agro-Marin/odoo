/** @odoo-module native */
export class BaseWorker {
    /**
     * @param {string} name
     * @param {boolean} [isShared] whether this code runs in a SharedWorker
     * (clients answered through the connecting MessagePort) or a dedicated
     * Worker (answered through the worker global scope). Derived from the
     * worker name when omitted — the derivation lives in ONE place
     * (`bus_worker_script.js` passes it explicitly); the fallback only
     * exists for the test mock, which instantiates this class directly.
     */
    constructor(name, isShared = Boolean(name?.includes("shared"))) {
        this.name = name;
        this.isShared = isShared;
        this.client = null; // only for testing purposes
    }

    handleMessage(event) {
        const { action } = event.data;
        if (action === "BASE:INIT") {
            if (this.isShared) {
                event.target.postMessage({ type: "BASE:INITIALIZED" });
            } else {
                (this.client || globalThis).postMessage({ type: "BASE:INITIALIZED" });
            }
        }
    }
}
