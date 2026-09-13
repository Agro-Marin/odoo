/** @odoo-module native */

import { markup } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

const log = makeLogger("website.service.google_maps");

registry.category("services").add("google_maps", {
    dependencies: ["notification"],
    start(env, deps) {
        log.lifecycle("google_maps service start");
        const notification = deps["notification"];
        let gMapsAPIKeyProm;
        let gMapsAPILoading;
        const promiseKeys = {};
        const promiseKeysResolves = {};
        let lastKey;
        window.odoo_gmaps_api_post_load = async function odoo_gmaps_api_post_load() {
            log.lifecycle("google_maps api loaded callback", () => ({
                pending: !!promiseKeysResolves[lastKey],
            }));
            promiseKeysResolves[lastKey]?.();
        }.bind(this);
        return {
            /**
             * @param {boolean} [refetch=false]
             */
            async getGMapsAPIKey(refetch) {
                if (refetch || !gMapsAPIKeyProm) {
                    log.logic("getGMapsAPIKey fetch", () => ({
                        refetch,
                        cached: !!gMapsAPIKeyProm,
                    }));
                    gMapsAPIKeyProm = (async () => {
                        try {
                            const endKeyRpc = log.perf("getGMapsAPIKey rpc");
                            const data = await rpc("/website/google_maps_api_key");
                            endKeyRpc();
                            return JSON.parse(data).google_maps_api_key || "";
                        } catch {
                            log.logic("getGMapsAPIKey failed: cache cleared");
                            gMapsAPIKeyProm = null;
                            return "";
                        }
                    })();
                }
                return gMapsAPIKeyProm;
            },
            /**
             * @param {boolean} [editableMode=false]
             * @param {boolean} [refetch=false]
             */
            async loadGMapsAPI(editableMode, refetch) {
                if (refetch || !gMapsAPILoading) {
                    gMapsAPILoading = (async () => {
                        try {
                            const key = await this.getGMapsAPIKey(refetch);
                            lastKey = key;
                            log.logic("loadGMapsAPI key resolved", () => ({
                                hasKey: !!key,
                                editableMode,
                                refetch,
                                scriptLoaded: !!promiseKeys[key],
                            }));

                            if (key) {
                                if (!promiseKeys[key]) {
                                    promiseKeys[key] = new Promise((resolve) => {
                                        promiseKeysResolves[key] = resolve;
                                    });
                                    const endLoadJS = log.perf("loadGMapsAPI loadJS");
                                    await loadJS(
                                        `https://maps.googleapis.com/maps/api/js?v=3.exp&libraries=places&callback=odoo_gmaps_api_post_load&key=${encodeURIComponent(
                                            key,
                                        )}`,
                                    );
                                    endLoadJS();
                                }
                                const endApiReady = log.perf(
                                    "loadGMapsAPI wait for api callback",
                                );
                                await promiseKeys[key];
                                endApiReady();
                                return key;
                            }
                            if (!editableMode && user.isAdmin) {
                                log.logic("loadGMapsAPI no key: warn admin");
                                const message = _t("Cannot load google map.");
                                const urlTitle = _t("Check your configuration.");
                                notification.add(
                                    markup`<div>
                                        <span>${message}</span><br/>
                                        <a href="/odoo/action-website.action_website_configuration">${urlTitle}</a>
                                    </div>`,
                                    { type: "warning", sticky: true },
                                );
                            }
                            return false;
                        } catch {
                            log.logic("loadGMapsAPI failed: cache cleared");
                            gMapsAPILoading = null;
                            return false;
                        }
                    })();
                }
                return gMapsAPILoading;
            },
            /**
             * @param {string} key
             * @returns {Promise<ApiKeyValidation>}
             */
            async validateGMapsApiKey(key) {
                if (key) {
                    try {
                        const endFetch = log.perf(
                            "validateGMapsApiKey fetch staticmap",
                        );
                        const response = await this.fetchGoogleMaps(key);
                        endFetch(() => ({ status: response.status }));
                        const isValid = response.status === 200;
                        return {
                            isValid,
                            message: isValid
                                ? undefined
                                : _t(
                                      "Invalid API Key. The following error was returned by Google: %(error)s",
                                      { error: await response.text() },
                                  ),
                        };
                    } catch {
                        log.logic("validateGMapsApiKey fetch failed");
                        return {
                            isValid: false,
                            message: _t("Check your connection and try again"),
                        };
                    }
                } else {
                    log.logic("validateGMapsApiKey empty key");
                    return { isValid: false };
                }
            },
            /**
             * @param {string} key
             * @returns {Promise<{ status: number }>}
             */
            async fetchGoogleMaps(key) {
                return await fetch(
                    `https://maps.googleapis.com/maps/api/staticmap?center=belgium&size=10x10&key=${encodeURIComponent(
                        key,
                    )}`,
                );
            },
        };
    },
});
