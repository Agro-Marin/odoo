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
 * @param {Deferred} settledDeferred
 * @returns {Promise<ServiceWorkerRegistration | undefined>}
 */
export async function registerServiceWorker(settledDeferred) {
    const { serviceWorker } = browser.navigator;
    let readyTimeoutId;
    try {
        if (!serviceWorker) {
            return;
        }
        const registration = await serviceWorker.register("/web/service-worker.js", {
            scope: "/odoo",
        });
        watchServiceWorkerUpdates(registration);
        if (registration.active && registration.active.state === "activated") {
            settledDeferred.resolve();
        } else {
            const sw =
                registration.installing || registration.waiting || registration.active;
            sw?.addEventListener("statechange", (e) => {
                if (/** @type {any} */ (e.target).state === "activated") {
                    settledDeferred.resolve();
                }
            });
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
        return registration;
    } catch (error) {
        console.error("Service worker registration failed, error:", error);
    } finally {
        browser.clearTimeout(readyTimeoutId);
        settledDeferred.resolve();
    }
}

class ServiceWorkerService {
    constructor() {
        /**
         * @type {Promise<void> & { resolve: (value?: any) => void, reject: (reason?: any) => void }}
         */
        const settledDeferred = new Deferred();
        /** @type {Promise<void>} */
        this.registrationSettled = settledDeferred;
        registerServiceWorker(settledDeferred);
    }
}

export const serviceWorkerService = {
    /** @returns {ServiceWorkerService} */
    start() {
        return new ServiceWorkerService();
    },
};

registry.category("services").add("service_worker", serviceWorkerService);
