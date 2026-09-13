/** @odoo-module native */
/* global google */

import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { GoogleMap } from "@website/snippets/s_google_map/google_map";

const log = makeLogger("website.snippet.s_google_map.edit");

const GoogleMapEdit = (I) =>
    class extends I {
        setup() {
            super.setup();
            this.canSpecifyKey = true;
            this.websiteEditService = this.services.website_edit;
            this.websiteMapService = this.services.website_map;
        }

        async willStart() {
            const endLoad = log.perf("willStart ensure google maps");
            const isLoaded =
                (typeof google === "object" &&
                    typeof google.maps === "object" &&
                    !this.websiteEditService.callShared(
                        "googleMapsOption",
                        "shouldRefetchApiKey",
                    )) ||
                (await this.loadGoogleMaps(false));
            endLoad({ isLoaded });
            if (isLoaded) {
                const endInit = log.perf("willStart initializeGoogleMaps");
                this.canStart = await this.websiteEditService.callShared(
                    "googleMapsOption",
                    "initializeGoogleMaps",
                    [this.el, google.maps],
                );
                endInit(() => ({ canStart: this.canStart }));
            } else {
                log.logic("willStart: google maps failed to load");
                this.websiteEditService.callShared(
                    "googleMapsOption",
                    "failedToInitializeGoogleMaps",
                    [this.el],
                );
            }
        }

        /**
         * @param {boolean} [forceReconfigure=false]
         * @returns {Promise<void>}
         */
        async loadGoogleMaps(forceReconfigure = false) {
            /** @type {string | undefined} */
            const apiKey = await this.websiteMapService.getGMapAPIKey(true);
            const apiKeyValidation =
                await this.websiteMapService.validateGMapApiKey(apiKey);
            const shouldReconfigure = forceReconfigure || !apiKeyValidation.isValid;
            log.logic("loadGoogleMaps: api key validated", () => ({
                hasKey: !!apiKey,
                isValid: apiKeyValidation.isValid,
                forceReconfigure,
                shouldReconfigure,
            }));
            let didReconfigure = false;
            if (shouldReconfigure) {
                didReconfigure = await this.websiteEditService.callShared(
                    "googleMapsOption",
                    "configureGMapsAPI",
                    apiKey,
                );
                if (!didReconfigure) {
                    log.logic(
                        "loadGoogleMaps: reconfiguration refused, removing snippet",
                    );
                    this.websiteEditService.callShared(
                        "remove",
                        "removeElement",
                        this.el,
                    );
                }
            }
            if (!shouldReconfigure || didReconfigure) {
                const shouldRefetch = this.websiteEditService.callShared(
                    "googleMapsOption",
                    "shouldRefetchApiKey",
                );
                return !!(await this.loadGoogleMapsAPIFromService(
                    shouldRefetch || didReconfigure,
                ));
            } else {
                return false;
            }
        }

        /**
         * @param {boolean} [shouldRefetch]
         * @returns {Promise<string|undefined>}
         */
        async loadGoogleMapsAPIFromService(shouldRefetch) {
            const endLoadApi = log.perf("loadGMapAPI", () => ({ shouldRefetch }));
            const apiKey = await this.websiteMapService.loadGMapAPI(
                true,
                shouldRefetch,
            );
            endLoadApi({ hasKey: !!apiKey });
            this.websiteEditService.callShared(
                "googleMapsOption",
                "shouldNotRefetchApiKey",
            );
            return !!apiKey;
        }
    };

registry.category("public.interactions.edit").add("website.google_map", {
    Interaction: GoogleMap,
    mixin: GoogleMapEdit,
});
