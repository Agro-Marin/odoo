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

/* Ideally, the service would directly add the event listener. Unfortunately, it happens sometimes that
 * the browser would trigger the event before the webclient (services, components, etc.) is even ready.
 * In that case, we have to get this event as soon as possible. The service can then verify if the event
 * is already stored in this variable, or add an event listener itself, to make sure the `_handleBeforeInstallPrompt`
 * function is called at the right moment, and can give the correct information to the service.
 */
/** @type {Event | null} */
let BEFOREINSTALLPROMPT_EVENT;
/** @type {((ev: Event) => void) | undefined} */
let REGISTER_BEFOREINSTALLPROMPT_EVENT;

browser.addEventListener("beforeinstallprompt", (ev) => {
    // This event is only triggered by the browser when the native prompt to install can be shown
    // This excludes incognito tabs, as well as visiting the website while the app is installed
    if (REGISTER_BEFOREINSTALLPROMPT_EVENT) {
        // service has been started before the event was triggered, update the service
        return REGISTER_BEFOREINSTALLPROMPT_EVENT(ev);
    } else {
        // store the event for later use
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
                // Installation page, use the path parameter in the URL
                state.startUrl =
                    "/" + new URL(browser.location.href).searchParams.get("path");
            } else {
                state.startUrl = browser.location.pathname;
            }
        }

        // The PWA can only be installed if the app is not already launched (display-mode standalone)
        // For Apple devices, PWA are supported on any mobile version of Safari, or in desktop since version 17
        // On Safari devices, the check is also done on the display-mode and we rely on the installationState to
        // decide whether we must show the prompt or not
        state.isSupportedOnBrowser =
            browser.BeforeInstallPromptEvent !== undefined ||
            (isBrowserSafari() &&
                !isDisplayStandalone() &&
                (isIOS() ||
                    (isMacOS() &&
                        Number(
                            browser.navigator.userAgent.match(/Version\/(\d+)/)?.[1],
                        ) >= 17)));

        const installationState = _getInstallationState();

        if (state.isSupportedOnBrowser) {
            if (BEFOREINSTALLPROMPT_EVENT) {
                _handleBeforeInstallPrompt(
                    BEFOREINSTALLPROMPT_EVENT,
                    installationState,
                );
                BEFOREINSTALLPROMPT_EVENT = null; // clear this variable as it is no longer useful
            }
            // If a user declines the prompt, the browser would triggered it once again. We must be able to catch it
            REGISTER_BEFOREINSTALLPROMPT_EVENT = (ev) => {
                // Re-read the persisted state: the boot-time snapshot predates
                // a dismissal recorded by show()/decline(), and using it here
                // would resurrect a prompt the user just dismissed.
                _handleBeforeInstallPrompt(ev, _getInstallationState());
            };
            if (isBrowserSafari()) {
                // since those platforms don't rely on the beforeinstallprompt event, we handle it ourselves
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
                // If this event is triggered with the installationState stored, it means that the app has been
                // removed since its installation. The prompt can be displayed, and the installation state is reset.
                if (!isDisplayStandalone()) {
                    // In Scoped Apps, the event might be triggered if a manifest with a different scope is available
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
                    // No manifest link on the page: don't fetch ``undefined``
                    // (which would GET the current page and throw in JSON.parse)
                    // and don't cache the failure — retry if a link appears.
                    return {};
                }
                const manifest = await get(href, "text");
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
                // since those platforms don't support a native installation prompt yet, we
                // show a custom dialog to explain how to pin the app to the application menu.
                // The callback is a dialog *option* (not a prop): it must fire on every
                // removal path (ESC, closeAll, ...), not just the explicit close button —
                // otherwise the dismissal is never persisted and the prompt reappears.
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

        return state;
    },
};
serviceRegistry.add("pwa", pwaService);
