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
        const onmessage = (/** @type {MessageEvent} */ event) => {
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

/**
 * Action paths that can receive files shared into the app, most-preferred
 * first (`sequence`). An app claims the share target by registering its own
 * path here; `web` has no business naming one, and did — the sole candidate was
 * spelled `"expenses"` in this file, so `hr_expense` owned a behaviour it could
 * not see and no other app could take part.
 */
const shareTargetRegistry = registry.category("share_target_apps");

shareTargetRegistry.addValidation((entry) => typeof entry === "string");

/**
 * @param {{ getApps: () => Record<string, any>[] }} menu
 * @returns {Record<string, any> | undefined}
 */
function findShareTargetApp(menu) {
    const apps = menu.getApps();
    for (const actionPath of shareTargetRegistry.getAll()) {
        const app = apps.find((app) => app.actionPath === actionPath);
        if (app) {
            return app;
        }
    }
}

/**
 * The `shareTarget` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * The share-target detection stays in the constructor rather than `start()`:
 * unlike `web_vitals` or `scss_error_display`, failing it does not mean there is
 * no service — `hasSharedFiles()` must still answer `false` for every caller.
 */
export class ShareTargetService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ menu: Object }} services
     */
    constructor(env, { menu }) {
        this.env = env;
        this.menu = menu;
        /** @type {File[] | null} */
        this.sharedFiles = null;
        if (
            browser.navigator.serviceWorker &&
            new URL(browser.location.href).searchParams.get("share_target") ===
                "trigger"
        ) {
            const app = findShareTargetApp(/** @type {any} */ (menu));
            if (app) {
                env.bus.addEventListener(
                    AppEvent.WEB_CLIENT_READY,
                    () => this.receiveSharedFiles(app),
                    { once: true },
                );
            }
        }
    }

    /** @param {any} app */
    async receiveSharedFiles(app) {
        try {
            this.sharedFiles = await getShareTargetDataFromServiceWorker();
            if (this.sharedFiles?.length) {
                await /** @type {any} */ (this.menu).selectMenu(app);
            }
        } catch (error) {
            console.warn("Failed to receive shared files", error);
        }
    }

    /** @return {boolean} */
    hasSharedFiles() {
        return !!this.sharedFiles?.length;
    }

    /** @return {null|File[]} */
    getSharedFilesToUpload() {
        const files = this.sharedFiles;
        this.sharedFiles = null;
        return files;
    }
}

export const shareTargetService = {
    dependencies: ["menu"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ menu: Object }} services
     * @returns {ShareTargetService}
     */
    start(env, services) {
        return new ShareTargetService(env, services);
    },
};

registry.category("services").add("shareTarget", shareTargetService);
