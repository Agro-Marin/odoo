// @ts-check
/** @odoo-module native */

/** @module @web/webclient/share_target/share_target_service */

import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
const SHARE_TARGET_ACK_TIMEOUT = 5000;

/**
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
     * @param {Object} env
     * @param {{ menu: Object }} services
     * @returns {{ hasSharedFiles: () => boolean, getSharedFilesToUpload: () => File[] | null }}
     */
    start(env, { menu }) {
        let sharedFiles = null;
        if (
            browser.navigator.serviceWorker &&
            new URL(browser.location.href).searchParams.get("share_target") ===
                "trigger"
        ) {
            const app = menu.getApps().find((app) => "expenses" === app.actionPath);
            if (app) {
                env.bus.addEventListener(
                    AppEvent.WEB_CLIENT_READY,
                    async () => {
                        try {
                            sharedFiles = await getShareTargetDataFromServiceWorker();
                            if (sharedFiles?.length) {
                                await menu.selectMenu(app);
                            }
                        } catch (error) {
                            console.warn("Failed to receive shared files", error);
                        }
                    },
                    { once: true },
                );
            }
        }
        return {
            /**
             * @return {boolean}
             */
            hasSharedFiles: () => !!sharedFiles?.length,
            /**
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
