/** @odoo-module native */

import { markup } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

registry.category("services").add("google_maps", {
    dependencies: ["notification"],
    start(env, deps) {
        const notification = deps["notification"];
        let gMapsAPIKeyProm;
        let gMapsAPILoading;
        const promiseKeys = {};
        const promiseKeysResolves = {};
        let lastKey;
        window.odoo_gmaps_api_post_load = async function odoo_gmaps_api_post_load() {
            promiseKeysResolves[lastKey]?.();
        }.bind(this);
        return {
            /**
             * @param {boolean} [refetch=false]
             */
            async getGMapsAPIKey(refetch) {
                if (refetch || !gMapsAPIKeyProm) {
                    gMapsAPIKeyProm = (async () => {
                        try {
                            const data = await rpc("/website/google_maps_api_key");
                            return JSON.parse(data).google_maps_api_key || "";
                        } catch {
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

                            if (key) {
                                if (!promiseKeys[key]) {
                                    promiseKeys[key] = new Promise((resolve) => {
                                        promiseKeysResolves[key] = resolve;
                                    });
                                    await loadJS(
                                        `https://maps.googleapis.com/maps/api/js?v=3.exp&libraries=places&callback=odoo_gmaps_api_post_load&key=${encodeURIComponent(
                                            key,
                                        )}`,
                                    );
                                }
                                await promiseKeys[key];
                                return key;
                            }
                            if (!editableMode && user.isAdmin) {
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
                        const response = await this.fetchGoogleMaps(key);
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
                        return {
                            isValid: false,
                            message: _t("Check your connection and try again"),
                        };
                    }
                } else {
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
