// @ts-check
/** @odoo-module native */

/** @module @web/webclient/service_worker_service */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";

const SERVICE_WORKER_UPDATE_INTERVAL = 6 * 60 * 60 * 1000;

const SERVICE_WORKER_READY_TIMEOUT = 20 * 1000;

/**
 * @param {ServiceWorkerRegistration} registration
 * @returns {void}
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
    registration.addEventListener("updatefound", () =>
        promoteWhenInstalled(registration.installing),
    );
    const checkForUpdate = () => registration.update().catch(() => {});
    browser.setInterval(checkForUpdate, SERVICE_WORKER_UPDATE_INTERVAL);
    browser.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            checkForUpdate();
        }
    });
}

/**
 * @param {Deferred} activatedDeferred
 * @returns {Promise<ServiceWorkerRegistration | undefined>}
 */
export async function registerServiceWorker(activatedDeferred) {
    const { serviceWorker } = browser.navigator;
    try {
        if (!serviceWorker) {
            return;
        }
        const registration = await serviceWorker.register("/web/service-worker.js", {
            scope: "/odoo",
        });
        watchServiceWorkerUpdates(registration);
        if (registration.active && registration.active.state === "activated") {
            activatedDeferred.resolve();
        } else {
            const sw =
                registration.installing || registration.waiting || registration.active;
            sw?.addEventListener("statechange", (e) => {
                if (/** @type {any} */ (e.target).state === "activated") {
                    activatedDeferred.resolve();
                }
            });
        }
        await Promise.race([
            serviceWorker.ready,
            new Promise((resolve) =>
                browser.setTimeout(resolve, SERVICE_WORKER_READY_TIMEOUT),
            ),
        ]);
        if (!serviceWorker.controller) {
            rpcBus.trigger(RpcEvent.CLEAR_CACHES);
        }
        return registration;
    } catch (error) {
        console.error("Service worker registration failed, error:", error);
    } finally {
        activatedDeferred.resolve();
    }
}

export const serviceWorkerService = {
    start() {
        /**
         * @type {Promise<void> & { resolve: (value?: any) => void, reject: (reason?: any) => void }}
         */
        const activatedDeferred = new Deferred();
        registerServiceWorker(activatedDeferred);
        return {
            /**
             * @type {Promise<void>}
             */
            activated: activatedDeferred,
        };
    },
};

registry.category("services").add("service_worker", serviceWorkerService);
