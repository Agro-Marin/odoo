/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";
import { session } from "@web/session";

export const WORKER_STATE = Object.freeze({
    UNINITIALIZED: "UNINITIALIZED",
    INITIALIZING: "INITIALIZING",
    INITIALIZED: "INITIALIZED",
    FAILED: "FAILED",
});

export class WorkerService {
    constructor(env, services) {
        this.params = services["bus.parameters"];
        this.worker = null;
        this.isUsingSharedWorker = Boolean(browser.SharedWorker);
        this._state = WORKER_STATE.UNINITIALIZED;
        this._failureWarned = false;
        this.connectionInitializedDeferred = new Deferred();
    }

    /**
     * What the service effectively ended up running, decided at RUNTIME (a
     * SharedWorker can fail and fall back to a dedicated Worker, or fail
     * entirely). Consumers that must adapt their strategy to the worker kind
     * (e.g. the multi_tab election) should await `ensureWorkerStarted()` /
     * `connectionInitializedDeferred` then read this — import-time feature
     * detection (`browser.SharedWorker` presence) is NOT equivalent.
     *
     * @returns {"shared" | "dedicated" | "failed" | null} null while the
     * outcome is not settled yet.
     */
    get workerKind() {
        if (this._state === WORKER_STATE.FAILED) {
            return "failed";
        }
        if (this._state !== WORKER_STATE.INITIALIZED) {
            return null;
        }
        return this.isUsingSharedWorker ? "shared" : "dedicated";
    }

    async startWorker() {
        this._state = WORKER_STATE.INITIALIZING;
        let workerURL = `${this.params.serverURL}/bus/websocket_worker_bundle?v=${session.websocket_worker_version}`;
        let blobURL = null;
        if (this.params.serverURL !== window.origin) {
            // Cross-origin scenario (e.g. prefork mode without a reverse proxy:
            // HTTP workers on port 8069, gevent on port 8072). Using importScripts
            // from a data: URL would be cross-origin and the browser omits the
            // session cookie, so Odoo cannot resolve the database and returns 404.
            // Instead, pre-fetch the bundle from the page context (which carries
            // the session cookie), then create a same-origin Blob URL for the Worker.
            try {
                const response = await fetch(workerURL, { credentials: "include" });
                if (!response.ok) {
                    throw new Error(
                        `Bundle fetch failed with status ${response.status}`,
                    );
                }
                const text = await response.text();
                blobURL = URL.createObjectURL(
                    new Blob([text], { type: "application/javascript" }),
                );
                workerURL = blobURL;
            } catch (e) {
                this._state = WORKER_STATE.FAILED;
                this.connectionInitializedDeferred.resolve();
                console.warn(
                    "Worker service failed to initialize: could not fetch worker bundle.",
                    e,
                );
                return;
            }
        }
        const workerClass = this.isUsingSharedWorker
            ? browser.SharedWorker
            : browser.Worker;
        try {
            this.worker = new workerClass(workerURL, {
                name: this.isUsingSharedWorker
                    ? "odoo:bus_shared_worker"
                    : "odoo:bus_worker",
                type: "module",
            });
        } catch (e) {
            // Worker construction can throw SYNCHRONOUSLY (CSP `worker-src`
            // restrictions, blob: SecurityError, missing Worker class).
            // Without this catch the rejection escapes `startWorker`,
            // `connectionInitializedDeferred` never settles and every caller
            // hangs forever. Route it through the same fallback/FAILED
            // transitions as an async worker error.
            this.onInitError(e);
            return;
        } finally {
            // The browser resolved (or rejected) the script fetch at
            // construction time: the blob URL served its purpose and keeping
            // it alive would leak the whole bundle text.
            if (blobURL) {
                URL.revokeObjectURL(blobURL);
            }
        }
        const worker = this.worker;
        worker.onerror = (e) => {
            // The abandoned SharedWorker keeps this handler after the
            // fallback replaced `this.worker` with a dedicated Worker. A late
            // second error from it must not mark the service FAILED while the
            // replacement is still initializing.
            if (worker === this.worker) {
                this.onInitError(e);
            }
        };
        this._registerHandler((ev) => {
            if (ev.data.type === "BASE:INITIALIZED") {
                this._state = WORKER_STATE.INITIALIZED;
                this.connectionInitializedDeferred.resolve();
            } else if (ev.data.type === "BUS:PING") {
                // Liveness probe from the websocket worker's dead-client
                // sweep: answering proves this tab is alive and unfrozen.
                this._send("BUS:PONG");
            }
        });
        if (this.isUsingSharedWorker) {
            this.worker.port.start();
        }
        this._send("BASE:INIT");
    }

    async ensureWorkerStarted() {
        if (this._state === WORKER_STATE.UNINITIALIZED) {
            this.startWorker();
        }
        await this.connectionInitializedDeferred;
    }

    onInitError(e) {
        // FIXME: SharedWorker can still fail for unknown reasons even when it is supported.
        if (this._state === WORKER_STATE.INITIALIZING && this.isUsingSharedWorker) {
            console.warn("Error while loading SharedWorker, fallback on Worker: ", e);
            this.isUsingSharedWorker = false;
            this.worker?.port?.close?.();
            this.startWorker();
        } else if (this._state === WORKER_STATE.INITIALIZING) {
            this._state = WORKER_STATE.FAILED;
            this.connectionInitializedDeferred.resolve();
            console.warn("Worker service failed to initialize: ", e);
        }
    }

    _registerHandler(handler) {
        if (this.isUsingSharedWorker) {
            this.worker.port.addEventListener("message", handler);
        } else {
            this.worker.addEventListener("message", handler);
        }
    }

    _send(action, data) {
        const message = { action, data };
        if (this.isUsingSharedWorker) {
            this.worker.port.postMessage(message);
        } else {
            this.worker.postMessage(message);
        }
    }

    /**
     * Send a message to the worker. If the worker is not yet started,
     * ignore the message. One should call `ensureWorkerStarted` if one
     * really needs the message to reach the worker.
     *
     * @param {String} action Action to be executed by the worker.
     * @param {Object|undefined} data Data required for the action to be
     * executed.
     */
    async send(action, data) {
        if (this._state === WORKER_STATE.UNINITIALIZED) {
            return;
        }
        await this.connectionInitializedDeferred;
        if (this._state === WORKER_STATE.FAILED) {
            this._warnFailedOnce();
            return;
        }
        this._send(action, data);
    }

    /**
     * Register a function to handle messages from the worker.
     *
     * @param {function} handler
     */
    async registerHandler(handler) {
        if (this._state === WORKER_STATE.UNINITIALIZED) {
            this.startWorker();
        }
        await this.connectionInitializedDeferred;
        if (this._state === WORKER_STATE.FAILED) {
            this._warnFailedOnce();
            return;
        }
        this._registerHandler(handler);
    }

    /**
     * Warn (once — the bus is chatty, one warning per send would flood the
     * console) that the service runs in FAILED mode: sends and handler
     * registrations are silently dropped.
     */
    _warnFailedOnce() {
        if (this._failureWarned) {
            return;
        }
        this._failureWarned = true;
        console.warn(
            "Worker service failed to initialize: worker messages are dropped" +
                " (this warning is only shown once).",
        );
    }

    get state() {
        return this._state;
    }
}

export const workerService = {
    dependencies: ["bus.parameters"],
    start(env, services) {
        return new WorkerService(env, services);
    },
};

registry.category("services").add("worker_service", workerService);
