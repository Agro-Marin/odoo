// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";

const SERVICE_WORKER_UPDATE_INTERVAL = 6 * 60 * 60 * 1000;

const SERVICE_WORKER_READY_TIMEOUT = 20 * 1000;

/**
 * @param {ServiceWorkerRegistration} registration
 * @returns {() => void}
 */
export function watchServiceWorkerUpdates(registration) {
    /** @param {ServiceWorker | null} worker */
    const promoteWhenInstalled = (worker) => {
        if (!worker) {
            return;
        }
        const promote = () => {
            if (worker.state === "installed" && registration.active) {
                worker.postMessage({ type: "SKIP_WAITING" });
            }
        };
        worker.addEventListener("statechange", promote);
        promote();
    };
    promoteWhenInstalled(registration.waiting);
    const onUpdateFound = () => promoteWhenInstalled(registration.installing);
    registration.addEventListener("updatefound", onUpdateFound);
    const checkForUpdate = () => registration.update().catch(() => {});
    const intervalId = browser.setInterval(
        checkForUpdate,
        SERVICE_WORKER_UPDATE_INTERVAL,
    );
    const onVisibilityChange = () => {
        if (document.visibilityState === "visible") {
            checkForUpdate();
        }
    };
    browser.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
        browser.clearInterval(intervalId);
        registration.removeEventListener("updatefound", onUpdateFound);
        browser.removeEventListener("visibilitychange", onVisibilityChange);
    };
}

/**
 * Hands back the disposer alongside the registration: `watchServiceWorkerUpdates`
 * installs a repeating timer and a document listener, and until this returned
 * one nothing could stop them — `env.destroy()` runs after every test that
 * starts this service, so they accumulated across a suite.
 *
 * `settledDeferred` still settles on every exit path, including the early one
 * where the browser has no service worker at all.
 *
 * @param {Deferred} settledDeferred
 * @returns {Promise<{
 *   registration: ServiceWorkerRegistration | undefined,
 *   stopWatching: () => void,
 * }>}
 */
export async function registerServiceWorker(settledDeferred) {
    const { serviceWorker } = browser.navigator;
    let readyTimeoutId;
    /** @type {() => void} */
    let stopWatching = () => {};
    /** @type {ServiceWorkerRegistration | undefined} */
    let registration;
    try {
        if (serviceWorker) {
            registration = await serviceWorker.register("/web/service-worker.js", {
                scope: "/odoo",
            });
            stopWatching = watchServiceWorkerUpdates(registration);
            if (registration.active && registration.active.state === "activated") {
                settledDeferred.resolve();
            } else {
                const sw =
                    registration.installing ||
                    registration.waiting ||
                    registration.active;
                if (sw) {
                    const onStateChange = (/** @type {Event} */ e) => {
                        if (/** @type {any} */ (e.target).state === "activated") {
                            sw.removeEventListener("statechange", onStateChange);
                            settledDeferred.resolve();
                        }
                    };
                    sw.addEventListener("statechange", onStateChange);
                }
            }
            await Promise.race([
                serviceWorker.ready,
                new Promise((resolve) => {
                    readyTimeoutId = browser.setTimeout(
                        resolve,
                        SERVICE_WORKER_READY_TIMEOUT,
                    );
                }),
            ]);
            if (!serviceWorker.controller) {
                rpcBus.trigger(RpcEvent.CLEAR_CACHES);
            }
        }
    } catch (error) {
        console.error("Service worker registration failed, error:", error);
    } finally {
        browser.clearTimeout(readyTimeoutId);
        settledDeferred.resolve();
    }
    return { registration, stopWatching };
}

class ServiceWorkerService {
    constructor() {
        /**
         * @type {Promise<void> & { resolve: (value?: any) => void, reject: (reason?: any) => void }}
         */
        const settledDeferred = new Deferred();
        /** @type {Promise<void>} */
        this.registrationSettled = settledDeferred;
        // `null` means "registration has not answered yet". `destroy()` writes a
        // no-op over it instead, so a disposer that arrives after teardown can
        // tell the two apart and stop itself.
        /** @type {(() => void) | null} */
        this.stopWatching = null;
        registerServiceWorker(settledDeferred).then(({ stopWatching }) => {
            if (this.stopWatching === null) {
                this.stopWatching = stopWatching;
            } else {
                stopWatching();
            }
        });
    }

    destroy() {
        this.stopWatching?.();
        this.stopWatching = () => {};
    }
}

export const serviceWorkerService = {
    /** @returns {ServiceWorkerService} */
    start() {
        return new ServiceWorkerService();
    },
};

registry.category("services").add("service_worker", serviceWorkerService);
