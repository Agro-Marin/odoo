// @ts-check
/** @odoo-module native */

/** @module @web/webclient/share_target/share_target_service - Service receiving shared files from the PWA service worker (Web Share Target API) */

import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
/** How long to wait for the service worker's ack before giving up (ms). */
const SHARE_TARGET_ACK_TIMEOUT = 5000;

/**
 * Request shared file data from the PWA service worker via postMessage.
 * Resolves once the worker responds with `odoo_share_target_ack`, with
 * `null` when the page is uncontrolled (e.g. after a hard refresh — see
 * webclient.js's registerServiceWorker) or when the worker never acks.
 * @returns {Promise<File[] | null>}
 */
const getShareTargetDataFromServiceWorker = () =>
    new Promise((resolve) => {
        const { serviceWorker } = browser.navigator;
        if (!serviceWorker.controller) {
            resolve(null);
            return;
        }
        const cleanup = () => {
            browser.clearTimeout(timeoutId);
            serviceWorker.removeEventListener("message", onmessage);
        };
        const onmessage = (event) => {
            if (event.data.action === "odoo_share_target_ack") {
                cleanup();
                resolve(event.data.shared_files);
            }
        };
        const timeoutId = browser.setTimeout(() => {
            cleanup();
            resolve(null);
        }, SHARE_TARGET_ACK_TIMEOUT);
        serviceWorker.addEventListener("message", onmessage);
        serviceWorker.controller.postMessage("odoo_share_target");
    });

export const shareTargetService = {
    dependencies: ["menu"],
    /**
     * If the page was opened via the Web Share Target API, listen for the
     * WEB_CLIENT_READY event, fetch shared files from the service worker,
     * and navigate to the expenses app.
     * @param {Object} env - Odoo environment
     * @param {{ menu: Object }} services - injected service dependencies
     * @returns {{ hasSharedFiles: () => boolean, getSharedFilesToUpload: () => File[] | null }}
     */
    start(env, { menu }) {
        let sharedFiles = null;
        if (
            browser.navigator.serviceWorker &&
            new URL(browser.location).searchParams.get("share_target") === "trigger"
        ) {
            const app = menu.getApps().find((app) => "expenses" === app.actionPath);
            if (app) {
                const clientReadyListener = async () => {
                    sharedFiles = await getShareTargetDataFromServiceWorker();
                    if (sharedFiles?.length) {
                        await menu.selectMenu(app);
                    }
                    env.bus.removeEventListener(
                        AppEvent.WEB_CLIENT_READY,
                        clientReadyListener,
                    );
                };
                env.bus.addEventListener(
                    AppEvent.WEB_CLIENT_READY,
                    clientReadyListener,
                );
            }
        }
        return {
            /**
             * Return true if we receive share target files from service worker
             * @return {boolean}
             */
            hasSharedFiles: () => !!sharedFiles?.length,
            /**
             * Return the shared files retrieve for upload
             * @return {null|File[]}
             */
            getSharedFilesToUpload: () => {
                const files = sharedFiles;
                sharedFiles = null;
                return files;
            },
        };
    },
};

registry.category("services").add("shareTarget", shareTargetService);
