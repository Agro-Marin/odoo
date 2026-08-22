// @ts-check
/** @odoo-module native */

import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import {
    isBrowserSafari,
    isDisplayStandalone,
    isIOS,
    isMacOS,
} from "@web/core/browser/feature_detection";
import {
    isPlainObject,
    readJSONStorage,
    writeJSONStorage,
} from "@web/core/browser/storage_json";
import { get } from "@web/core/network/http_service";
import { registry } from "@web/core/registry";

import { InstallPrompt } from "./install_prompt.js";

const serviceRegistry = registry.category("services");

const INSTALLATION_STATE_KEY = "pwaService.installationState";

/**
 * @type {Event | null}
 */
let BEFOREINSTALLPROMPT_EVENT;
/** @type {((ev: Event) => void) | undefined} */
let REGISTER_BEFOREINSTALLPROMPT_EVENT;

browser.addEventListener("beforeinstallprompt", (ev) => {
    if (REGISTER_BEFOREINSTALLPROMPT_EVENT) {
        return REGISTER_BEFOREINSTALLPROMPT_EVENT(ev);
    } else {
        BEFOREINSTALLPROMPT_EVENT = ev;
    }
});

export function _resetPwaInstallPrompt() {
    BEFOREINSTALLPROMPT_EVENT = null;
    REGISTER_BEFOREINSTALLPROMPT_EVENT = undefined;
}

class PwaService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ dialog: any }} services
     */
    constructor(env, { dialog }) {
        this.env = env;
        this.dialog = dialog;
        /** @type {any} */
        this._manifest = undefined;
        /** @type {Promise<any> | null} */
        this._manifestPromise = null;
        /** @type {any} */
        this.nativePrompt = undefined;
        /** @type {((ev: Event) => void) | undefined} */
        this._registeredPrompt = undefined;

        this.canPromptToInstall = false;
        this.isAvailable = false;
        this.isScopedApp = browser.location.href.includes("/scoped_app");
        this.isSupportedOnBrowser = false;
        this.startUrl = "/odoo";
    }

    setup() {
        if (this.isScopedApp) {
            if (browser.location.pathname === "/scoped_app") {
                const path = new URL(browser.location.href).searchParams.get("path");
                this.startUrl = path ? `/${path}` : this.startUrl;
            } else {
                this.startUrl = browser.location.pathname;
            }
        }

        this.isSupportedOnBrowser =
            browser.BeforeInstallPromptEvent !== undefined ||
            (isBrowserSafari() &&
                !isDisplayStandalone() &&
                (isIOS() ||
                    (isMacOS() &&
                        Number(
                            browser.navigator.userAgent.match(/Version\/(\d+)/)?.[1],
                        ) >= 17)));

        const installationState = this._getInstallationState();

        if (this.isSupportedOnBrowser) {
            if (BEFOREINSTALLPROMPT_EVENT) {
                this._handleBeforeInstallPrompt(
                    BEFOREINSTALLPROMPT_EVENT,
                    installationState,
                );
                BEFOREINSTALLPROMPT_EVENT = null;
            }
            this._registeredPrompt = (/** @type {Event} */ ev) =>
                this._handleBeforeInstallPrompt(ev, this._getInstallationState());
            REGISTER_BEFOREINSTALLPROMPT_EVENT = this._registeredPrompt;
            if (isBrowserSafari()) {
                this.canPromptToInstall = installationState !== "dismissed";
                this.isAvailable = true;
            }
        }
    }

    /**
     * @returns {Record<string, string>}
     */
    _readState() {
        return readJSONStorage(INSTALLATION_STATE_KEY, {
            fallback: /** @type {Record<string, string>} */ ({}),
            validate: isPlainObject,
        });
    }

    /**
     * @param {string} [scope]
     * @returns {string}
     */
    _getInstallationState(scope = this.startUrl) {
        return this._readState()[scope] || "";
    }

    /**
     * @param {string} value
     */
    _setInstallationState(value) {
        const ls = this._readState();
        ls[this.startUrl] = value;
        writeJSONStorage(INSTALLATION_STATE_KEY, ls);
    }

    _removeInstallationState() {
        const ls = this._readState();
        delete ls[this.startUrl];
        writeJSONStorage(INSTALLATION_STATE_KEY, ls);
    }

    /**
     * @param {Event} ev
     * @param {string} installationState
     */
    _handleBeforeInstallPrompt(ev, installationState) {
        this.nativePrompt = ev;
        if (installationState === "accepted") {
            if (!isDisplayStandalone()) {
                this._removeInstallationState();
            }
        }
        this.canPromptToInstall = installationState !== "dismissed";
        this.isAvailable = true;
    }

    /**
     * @returns {Promise<Object>}
     */
    async getManifest() {
        if (this._manifest) {
            return this._manifest;
        }
        if (!this._manifestPromise) {
            const href = document
                .querySelector("link[rel=manifest]")
                ?.getAttribute("href");
            if (!href) {
                return {};
            }
            this._manifestPromise = get(href, "text", { rejectHtml: true })
                .then((/** @type {string} */ manifest) => {
                    this._manifest = JSON.parse(manifest);
                    return this._manifest;
                })
                .finally(() => {
                    this._manifestPromise = null;
                });
        }
        return this._manifestPromise;
    }

    /**
     * @param {string} scope
     * @returns {boolean}
     */
    hasScopeBeenInstalled(scope) {
        return this._getInstallationState(scope) === "accepted";
    }

    /**
     * @param {{ onDone?: Function }} [options]
     */
    async show({ onDone } = {}) {
        if (!this.isAvailable) {
            return;
        }
        if (this.nativePrompt) {
            const prompt = this.nativePrompt;
            this.nativePrompt = null;
            try {
                const res = await prompt.prompt();
                this._setInstallationState(res.outcome);
                if (onDone) {
                    onDone(res);
                }
            } finally {
                this.canPromptToInstall = false;
            }
        } else if (isBrowserSafari()) {
            this.dialog.add(
                InstallPrompt,
                {},
                {
                    onClose: () => {
                        if (onDone) {
                            onDone({});
                        }
                        this.decline();
                    },
                },
            );
        }
    }

    decline() {
        this._setInstallationState("dismissed");
        this.canPromptToInstall = false;
    }

    destroy() {
        if (REGISTER_BEFOREINSTALLPROMPT_EVENT === this._registeredPrompt) {
            REGISTER_BEFOREINSTALLPROMPT_EVENT = undefined;
        }
    }
}

export const pwaService = {
    dependencies: ["dialog"],
    async: ["getManifest", "show"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ dialog: any }} services
     * @returns {PwaService}
     */
    start(env, services) {
        const service = reactive(new PwaService(env, services));
        service.setup();
        return service;
    },
};

serviceRegistry.add("pwa", pwaService);
