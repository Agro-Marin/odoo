/** @odoo-module native */
import { markup } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

export const websiteMapService = {
    dependencies: ["public.interactions", "notification"],
    start(env, deps) {
        const publicInteractions = deps["public.interactions"];
        const notification = deps["notification"];
        let gmapAPIKeyProm;
        let gmapAPILoading;
        const promiseKeys = {};
        const promiseKeysResolves = {};
        let lastKey;
        window.odoo_gmap_api_post_load = async function odoo_gmap_api_post_load() {
            for (const el of document.querySelectorAll("section.s_google_map")) {
                publicInteractions.stopInteractions(el);
                publicInteractions.startInteractions(el);
            }
            promiseKeysResolves[lastKey]?.();
        }.bind(this);
        return {
            /**
             * @param {boolean} [refetch=false]
             */
            async getGMapAPIKey(refetch) {
                if (refetch || !gmapAPIKeyProm) {
                    gmapAPIKeyProm = (async () => {
                        try {
                            const data = await rpc("/website/google_maps_api_key");
                            return JSON.parse(data).google_maps_api_key || "";
                        } catch {
                            gmapAPIKeyProm = null;
                            return "";
                        }
                    })();
                }
                return gmapAPIKeyProm;
            },
            /**
             * @param {boolean} [editableMode=false]
             * @param {boolean} [refetch=false]
             */
            async loadGMapAPI(editableMode, refetch) {
                if (refetch || !gmapAPILoading) {
                    gmapAPILoading = (async () => {
                        try {
                            const key = await this.getGMapAPIKey(refetch);
                            lastKey = key;

                            if (key) {
                                if (!promiseKeys[key]) {
                                    promiseKeys[key] = new Promise((resolve) => {
                                        promiseKeysResolves[key] = resolve;
                                    });
                                    await loadJS(
                                        `https://maps.googleapis.com/maps/api/js?v=3.exp&libraries=places&callback=odoo_gmap_api_post_load&key=${encodeURIComponent(
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
                            gmapAPILoading = null;
                            return false;
                        } catch {
                            gmapAPILoading = null;
                            return false;
                        }
                    })();
                }
                return gmapAPILoading;
            },
            /**
             * @param {string} key
             * @returns {Promise<ApiKeyValidation>}
             */
            async validateGMapApiKey(key) {
                if (key) {
                    try {
                        const response = await this.fetchGoogleMap(key);
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
            async fetchGoogleMap(key) {
                return await fetch(
                    `https://maps.googleapis.com/maps/api/staticmap?center=belgium&size=10x10&key=${encodeURIComponent(
                        key,
                    )}`,
                );
            },
        };
    },
};

registry.category("services").add("website_map", websiteMapService);
