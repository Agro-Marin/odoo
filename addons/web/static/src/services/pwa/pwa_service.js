// @ts-check
/** @odoo-module native */

/** @module @web/services/pwa/pwa_service */

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
import { registry } from "@web/core/registry";
import { get } from "@web/services/http_service";

import { InstallPrompt } from "./install_prompt.js";

const serviceRegistry = registry.category("services");

const INSTALLATION_STATE_KEY = "pwaService.installationState";

/**
 * The browser may fire `beforeinstallprompt` before any service exists, so the
 * event is parked here at module scope and claimed by the next service to
 * start. That latch outlives every env, which is why it needs an explicit
 * reset: without one a parked event survives into whatever runs next.
 *
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

/**
 * @typedef {Object} PwaServiceState
 * @property {boolean} canPromptToInstall
 * @property {boolean} isAvailable
 * @property {boolean} isScopedApp
 * @property {boolean} isSupportedOnBrowser
 * @property {string} startUrl
 * @property {() => void} decline
 * @property {() => Promise<Object>} getManifest
 * @property {(scope: string) => boolean} hasScopeBeenInstalled
 * @property {(options?: { onDone?: Function }) => Promise<void>} show
 */

export const pwaService = {
    dependencies: ["dialog"],
    async: ["getManifest", "show"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ dialog: any }} services
     * @returns {PwaServiceState}
     */
    start(env, { dialog }) {
        /** @type {any} */
        let _manifest;
        /**
         * @type {Promise<any> | null}
         */
        let _manifestPromise = null;
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
            destroy() {
                if (REGISTER_BEFOREINSTALLPROMPT_EVENT === handleRegisteredPrompt) {
                    REGISTER_BEFOREINSTALLPROMPT_EVENT = undefined;
                }
            },
        });

        /**
         * @returns {Record<string, string>}
         */
        function _readState() {
            return readJSONStorage(INSTALLATION_STATE_KEY, {
                fallback: /** @type {Record<string, string>} */ ({}),
                validate: isPlainObject,
            });
        }

        /**
         * @param {string} [scope]
         * @returns {string}
         */
        function _getInstallationState(scope = state.startUrl) {
            return _readState()[scope] || "";
        }

        /**
         * @param {string} value
         */
        function _setInstallationState(value) {
            const ls = _readState();
            ls[state.startUrl] = value;
            writeJSONStorage(INSTALLATION_STATE_KEY, ls);
        }

        function _removeInstallationState() {
            const ls = _readState();
            delete ls[state.startUrl];
            writeJSONStorage(INSTALLATION_STATE_KEY, ls);
        }

        if (state.isScopedApp) {
            if (browser.location.pathname === "/scoped_app") {
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
         * @param {Event} ev
         * @param {string} installationState
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
         * @returns {Promise<Object>}
         */
        async function getManifest() {
            if (_manifest) {
                return _manifest;
            }
            if (!_manifestPromise) {
                const href = document
                    .querySelector("link[rel=manifest]")
                    ?.getAttribute("href");
                if (!href) {
                    return {};
                }
                _manifestPromise = get(href, "text", { rejectHtml: true })
                    .then((/** @type {string} */ manifest) => {
                        _manifest = JSON.parse(manifest);
                        return _manifest;
                    })
                    .finally(() => {
                        _manifestPromise = null;
                    });
            }
            return _manifestPromise;
        }

        /**
         * @param {string} scope
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
                const prompt = nativePrompt;
                nativePrompt = null;
                const res = await prompt.prompt();
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

        function decline() {
            _setInstallationState("dismissed");
            state.canPromptToInstall = false;
        }

        return state;
    },
};
serviceRegistry.add("pwa", pwaService);
