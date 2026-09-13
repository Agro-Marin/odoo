/** @odoo-module native */
import { markup } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

const log = makeLogger("website.service.map");

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
            log.pipeline("gmap api post load: restarting map interactions", () => ({
                maps: document.querySelectorAll("section.s_google_map").length,
                hasResolver: !!promiseKeysResolves[lastKey],
            }));
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
                log.logic("getGMapAPIKey", () => ({
                    refetch,
                    cached: !!gmapAPIKeyProm,
                }));
                if (refetch || !gmapAPIKeyProm) {
                    gmapAPIKeyProm = (async () => {
                        try {
                            const endKey = log.perf("getGMapAPIKey rpc");
                            const data = await rpc("/website/google_maps_api_key");
                            endKey();
                            return JSON.parse(data).google_maps_api_key || "";
                        } catch {
                            log.logic(
                                "getGMapAPIKey: rpc or parse failed, cache reset",
                            );
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
                log.logic("loadGMapAPI", () => ({
                    editableMode,
                    refetch,
                    loading: !!gmapAPILoading,
                }));
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
                                    const endLoadJS = log.perf("loadGMapAPI loadJS");
                                    await loadJS(
                                        `https://maps.googleapis.com/maps/api/js?v=3.exp&libraries=places&callback=odoo_gmap_api_post_load&key=${encodeURIComponent(
                                            key,
                                        )}`,
                                    );
                                    endLoadJS();
                                }
                                const endReady = log.perf(
                                    "loadGMapAPI await api ready",
                                );
                                await promiseKeys[key];
                                endReady();
                                return key;
                            }
                            log.logic("loadGMapAPI: no API key", () => ({
                                editableMode,
                                notifyAdmin: !editableMode && user.isAdmin,
                            }));
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
                            log.logic("loadGMapAPI: loading failed, cache reset");
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
                        const endValidate = log.perf("validateGMapApiKey fetch");
                        const response = await this.fetchGoogleMap(key);
                        const isValid = response.status === 200;
                        endValidate({ status: response.status, isValid });
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
                        log.logic("validateGMapApiKey: fetch failed");
                        return {
                            isValid: false,
                            message: _t("Check your connection and try again"),
                        };
                    }
                } else {
                    log.logic("validateGMapApiKey: empty key");
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
