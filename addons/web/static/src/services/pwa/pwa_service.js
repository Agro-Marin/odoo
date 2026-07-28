// @ts-check
/** @odoo-module native */

/** @module @web/services/pwa/pwa_service - PWA install service: manages beforeinstallprompt, manifest fetch, and Safari fallback */

import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import {
    isBrowserSafari,
    isDisplayStandalone,
    isIOS,
    isMacOS,
} from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { get } from "@web/services/http_service";

import { InstallPrompt } from "./install_prompt.js";

const serviceRegistry = registry.category("services");

/** @type {Event | null} */
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

/**
 * @typedef {Object} PwaServiceState
 * @property {boolean} canPromptToInstall - whether the install prompt can be shown
 * @property {boolean} isAvailable - whether PWA installation is supported and applicable
 * @property {boolean} isScopedApp - whether we're on a scoped app page
 * @property {boolean} isSupportedOnBrowser - whether the browser supports PWA install
 * @property {string} startUrl - the start URL for the PWA
 * @property {() => void} decline - mark the install prompt as dismissed
 * @property {() => Promise<Object>} getManifest - fetch and cache the web manifest
 * @property {(scope: string) => boolean} hasScopeBeenInstalled - check if a scope was previously installed
 * @property {(options?: { onDone?: Function }) => Promise<void>} show - show the install prompt
 */

/**
 * Service managing Progressive Web App installation state and prompts.
 * Handles both native (Chrome) and Safari-specific install flows.
 */
export const pwaService = {
    dependencies: ["dialog"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ dialog: any }} services
     * @returns {PwaServiceState}
     */
    start(env, { dialog }) {
        /** @type {any} */
        let _manifest;
        /** @type {any} */
        let nativePrompt;

        const state = reactive({
            canPromptToInstall: false,
            isAvailable: false,
            isScopedApp: browser.location.href.includes("/scoped_app"),
            isSupportedOnBrowser: false,
            startUrl: "/odoo",
            decline,
            getManifest,
            hasScopeBeenInstalled,
            show,
        });

        /**
         * Read the whole persisted state map from localStorage.
         * A corrupted value must not throw: at service start an unguarded
         * parse error would take pwa (and its dependents) down on every
         * boot, and later in show()/decline() it would break the install
         * flow. Treat it as no state (the next write resets it).
         * @returns {Record<string, string>}
         */
        function _readState() {
            try {
                return (
                    JSON.parse(
                        browser.localStorage.getItem("pwaService.installationState"),
                    ) || {}
                );
            } catch {
                return {};
            }
        }

        /**
         * Read the installation state from localStorage for a given scope.
         * @param {string} [scope] - defaults to the current startUrl
         * @returns {string} "accepted", "dismissed", or ""
         */
        function _getInstallationState(scope = state.startUrl) {
            return _readState()[scope] || "";
        }

        /**
         * Persist the installation state for the current scope.
         * @param {string} value - "accepted" or "dismissed"
         */
        function _setInstallationState(value) {
            const ls = _readState();
            ls[state.startUrl] = value;
            browser.localStorage.setItem(
                "pwaService.installationState",
                JSON.stringify(ls),
            );
        }

        /** Remove the persisted installation state for the current scope. */
        function _removeInstallationState() {
            const ls = _readState();
            delete ls[state.startUrl];
            browser.localStorage.setItem(
                "pwaService.installationState",
                JSON.stringify(ls),
            );
        }

        if (state.isScopedApp) {
            if (browser.location.pathname === "/scoped_app") {
                // `searchParams.get` returns null when `path` is absent, which
                // concatenated into the literal scope "/null" — a key that then
                // got its own persisted installation state.
                const path = new URL(browser.location.href).searchParams.get("path");
                state.startUrl = path ? `/${path}` : state.startUrl;
            } else {
                state.startUrl = browser.location.pathname;
            }
        }

        state.isSupportedOnBrowser =
            browser.BeforeInstallPromptEvent !== undefined ||
            (isBrowserSafari() &&
                !isDisplayStandalone() &&
                (isIOS() ||
                    (isMacOS() &&
                        Number(
                            browser.navigator.userAgent.match(/Version\/(\d+)/)?.[1],
                        ) >= 17)));

        /** @param {Event} ev */
        const handleRegisteredPrompt = (ev) => {
            _handleBeforeInstallPrompt(ev, _getInstallationState());
        };

        const installationState = _getInstallationState();

        if (state.isSupportedOnBrowser) {
            if (BEFOREINSTALLPROMPT_EVENT) {
                _handleBeforeInstallPrompt(
                    BEFOREINSTALLPROMPT_EVENT,
                    installationState,
                );
                BEFOREINSTALLPROMPT_EVENT = null;
            }
            REGISTER_BEFOREINSTALLPROMPT_EVENT = handleRegisteredPrompt;
            if (isBrowserSafari()) {
                state.canPromptToInstall = installationState !== "dismissed";
                state.isAvailable = true;
            }
        }

        /**
         * Handle the browser's `beforeinstallprompt` event.
         * @param {Event} ev - the BeforeInstallPromptEvent
         * @param {string} installationState - current persisted state
         */
        function _handleBeforeInstallPrompt(ev, installationState) {
            nativePrompt = ev;
            if (installationState === "accepted") {
                if (!isDisplayStandalone()) {
                    _removeInstallationState();
                }
            }
            state.canPromptToInstall = installationState !== "dismissed";
            state.isAvailable = true;
        }

        /**
         * Fetch and cache the web app manifest.
         * @returns {Promise<Object>} parsed manifest JSON
         */
        async function getManifest() {
            if (!_manifest) {
                const href = document
                    .querySelector("link[rel=manifest]")
                    ?.getAttribute("href");
                if (!href) {
                    return {};
                }
                const manifest = await get(href, "text", { rejectHtml: true });
                _manifest = JSON.parse(manifest);
            }
            return _manifest;
        }

        /**
         * Check if a scope was previously installed (based on localStorage state).
         * Does not guarantee the app is still installed on the device.
         * @param {string} scope - the PWA scope to check
         * @returns {boolean}
         */
        function hasScopeBeenInstalled(scope) {
            return _getInstallationState(scope) === "accepted";
        }

        async function show(/** @type {{onDone?: Function}} */ { onDone } = {}) {
            if (!state.isAvailable) {
                return;
            }
            if (nativePrompt) {
                const res = await nativePrompt.prompt();
                _setInstallationState(res.outcome);
                state.canPromptToInstall = false;
                if (onDone) {
                    onDone(res);
                }
            } else if (isBrowserSafari()) {
                dialog.add(
                    InstallPrompt,
                    {},
                    {
                        onClose: () => {
                            if (onDone) {
                                onDone({});
                            }
                            decline();
                        },
                    },
                );
            }
        }

        /** Mark the install prompt as dismissed and hide it. */
        function decline() {
            _setInstallationState("dismissed");
            state.canPromptToInstall = false;
        }

        /**
         * Release the module-level hook back to the "stash the event" path.
         * `REGISTER_BEFOREINSTALLPROMPT_EVENT` is a module singleton pointing
         * into this env's closure: left set, it keeps a torn-down env alive and
         * swallows the event for whichever env starts next, which then never
         * learns the app is installable.
         */
        state.destroy = () => {
            if (REGISTER_BEFOREINSTALLPROMPT_EVENT === handleRegisteredPrompt) {
                REGISTER_BEFOREINSTALLPROMPT_EVENT = undefined;
            }
        };

        return state;
    },
};
serviceRegistry.add("pwa", pwaService);
