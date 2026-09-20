/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Deferred } from "@web/core/utils/concurrency";
import { renderToElement } from "@web/core/utils/render";

import { GoogleMapsApiKeyDialog } from "./google_maps_api_key_dialog.js";
import { GoogleMapsOption } from "./google_maps_option.js";

const log = makeLogger("website.builder.plugin.google_maps_option");

/**
 * @typedef {Object} Place
 * @property {string} [formatted_address]
 * @property {Object} [geometry]
 * @property {Object} [geometry.location]
 * @property {function():number} geometry.location.lat
 * @property {function():number} geometry.location.lng
 */
/**
 * @typedef {`${number},${number}`} Coordinates
 */
/**
 * @typedef {{ isValid: boolean, message?: string }} ApiKeyValidation
 */

/**
 * @typedef { Object } GoogleMapsOptionShared
 * @property { GoogleMapsOptionPlugin['configureGMapsAPI'] } configureGMapsAPI
 * @property { GoogleMapsOptionPlugin['initializeGoogleMaps'] } initializeGoogleMaps
 * @property { GoogleMapsOptionPlugin['failedToInitializeGoogleMaps'] } failedToInitializeGoogleMaps
 * @property { GoogleMapsOptionPlugin['shouldRefetchApiKey'] } shouldRefetchApiKey
 * @property { GoogleMapsOptionPlugin['shouldNotRefetchApiKey'] } shouldNotRefetchApiKey
 * @property { GoogleMapsOptionPlugin['commitPlace'] } commitPlace
 * @property { GoogleMapsOptionPlugin['getPlace'] } getPlace
 * @property { GoogleMapsOptionPlugin['getMapsAPI'] } getMapsAPI
 */

export class GoogleMapsOptionPlugin extends Plugin {
    static id = "googleMapsOption";
    static dependencies = ["history", "edit_interaction"];
    static shared = [
        "configureGMapsAPI",
        "initializeGoogleMaps",
        "failedToInitializeGoogleMaps",
        "shouldRefetchApiKey",
        "shouldNotRefetchApiKey",
        "commitPlace",
        "getPlace",
        "getMapsAPI",
    ];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [GoogleMapsOption],
        so_content_addition_selector: [".s_google_map"],
        on_snippet_dropped_handlers: this.onSnippetDropped.bind(this),
        builder_actions: {
            ResetMapColorAction,
            ShowDescriptionAction,
        },
        keep_overlay_options: (el) => el.matches(".s_google_map"),
    };

    setup() {
        this.websiteService = this.services.website;
        this.dialog = this.services.dialog;
        this.orm = this.services.orm;
        this.notification = this.services.notification;

        /** @type {Map<Coordinates, Place>} */
        this.gpsMapCache = new Map();

        /** @type {Map<HTMLElement, Deferred} */
        this.recentlyDroppedSnippetDeferredInit = new Map();
        log.lifecycle("GoogleMapsOptionPlugin setup");
    }

    async onSnippetDropped({ snippetEl }) {
        if (snippetEl.matches(".s_google_map")) {
            const deferredInit = new Deferred();
            this.recentlyDroppedSnippetDeferredInit.set(snippetEl, deferredInit);
            log.lifecycle("GoogleMapsOptionPlugin map dropped: restart interactions");
            this.dependencies.edit_interaction.restartInteractions(snippetEl);
            const endInit = log.perf(
                "GoogleMapsOptionPlugin wait for dropped map init",
            );
            const initSuccess = await deferredInit;
            endInit(() => ({ initSuccess }));
            this.recentlyDroppedSnippetDeferredInit.delete(snippetEl);
            if (!initSuccess) {
                log.logic("GoogleMapsOptionPlugin map init failed: cancel drop");
                return true;
            }
        }
    }

    failedToInitializeGoogleMaps(editingElement) {
        log.logic("GoogleMapsOptionPlugin failed to initialize", () => ({
            pendingDrop: this.recentlyDroppedSnippetDeferredInit.has(editingElement),
        }));
        this.recentlyDroppedSnippetDeferredInit.get(editingElement)?.resolve(false);
    }

    getMapsAPI() {
        return this.mapsAPI;
    }

    async initializeGoogleMaps(editingElement, mapsAPI) {
        this.recentlyDroppedSnippetDeferredInit.get(editingElement)?.resolve(true);
        if (mapsAPI) {
            log.lifecycle("GoogleMapsOptionPlugin maps api available", () => ({
                hasPlaces: !!mapsAPI.places,
            }));
            this.mapsAPI = mapsAPI;
            this.placesAPI = mapsAPI.places;
        }
        return (
            !!this.placesAPI &&
            !!(await this.getPlace(editingElement, editingElement.dataset.mapGps))
        );
    }

    /**
     * @param {Element} editingElement
     * @param {Coordinates} coordinates
     * @returns {Promise<Place | undefined>}
     */
    async getPlace(editingElement, coordinates) {
        const endSearch = log.perf("GoogleMapsOptionPlugin getPlace", () => ({
            coordinates,
        }));
        const place = await this.nearbySearch(coordinates);
        endSearch(() => ({ found: !!place, error: place?.error }));
        if (place?.error && !this.isGoogleMapsErrorBeingHandled) {
            log.logic("GoogleMapsOptionPlugin getPlace error", () => ({
                error: place.error,
            }));
            this.notifyGMapsError(editingElement);
        } else if (!place && !this.isGoogleMapsErrorBeingHandled) {
            log.logic(
                "GoogleMapsOptionPlugin getPlace no place: undo initialize",
                () => ({
                    canUndo: !!this.undoInitialize,
                }),
            );
            this.undoInitialize?.();
        } else {
            return place;
        }
    }

    /**
     * @param {Element} editingElement
     * @param {Place} place
     */
    commitPlace(editingElement, place) {
        if (place?.geometry) {
            const location = place.geometry.location;
            /** @type {Coordinates} */
            const coordinates = `(${location.lat()},${location.lng()})`;
            this.gpsMapCache.set(coordinates, place);
            /** @type {{mapGps: Coordinates, pinAddress: string}} */
            const currentMapData = editingElement.dataset;
            const { mapGps, pinAddress } = currentMapData;
            if (mapGps !== coordinates || pinAddress !== place.formatted_address) {
                log.logic("GoogleMapsOptionPlugin commitPlace: map moved", () => ({
                    from: mapGps,
                    to: coordinates,
                }));
                editingElement.dataset.mapGps = coordinates;
                editingElement.dataset.pinAddress = place.formatted_address;
                this.dispatchTo("content_manually_updated_handlers", editingElement);
                this.dependencies.history.addStep();
            }
        }
    }

    /**
     * @param {string} [apiKey]
     * @returns {Promise<boolean>}
     */
    async configureGMapsAPI(apiKey) {
        this.undoInitialize = this.dependencies.history.makeSavePoint();
        /** @type {number} */
        const websiteId = this.websiteService.currentWebsite.id;
        log.lifecycle("GoogleMapsOptionPlugin open api key dialog", () => ({
            hasApiKey: !!apiKey,
        }));

        /** @type {boolean} */
        const didReconfigure = await new Promise((resolve) => {
            let isInvalidated = false;
            this.dialog.add(
                GoogleMapsApiKeyDialog,
                {
                    originalApiKey: apiKey,
                    onSave: async (newApiKey) => {
                        const endWrite = log.perf(
                            "GoogleMapsOptionPlugin write google_maps_api_key",
                        );
                        await this.orm.write("website", [websiteId], {
                            google_maps_api_key: newApiKey,
                        });
                        endWrite();
                        this.shouldRefetchApiKey = false;
                        isInvalidated = true;
                    },
                },
                {
                    onClose: () => resolve(isInvalidated),
                },
            );
        });
        log.logic("GoogleMapsOptionPlugin api key dialog closed", () => ({
            didReconfigure,
        }));
        return didReconfigure;
    }

    /**
     * @param {Coordinates} coordinates
     * @returns {Promise<Place|{ error: string }|undefined>}
     */
    async nearbySearch(coordinates) {
        const place = this.gpsMapCache.get(coordinates);
        if (place) {
            log.logic("GoogleMapsOptionPlugin nearbySearch cache hit", () => ({
                coordinates,
            }));
            return place;
        }

        const p = coordinates.substring(1).slice(0, -1).split(",");
        const location = new this.mapsAPI.LatLng(p[0] || 0, p[1] || 0);
        return new Promise((resolve) => {
            const placesService = new this.placesAPI.PlacesService(
                document.createElement("div"),
            );
            placesService.nearbySearch(
                {
                    location,
                    radius: 1,
                },
                (results, status) => {
                    const GMAPS_CRITICAL_ERRORS = [
                        this.placesAPI.PlacesServiceStatus.REQUEST_DENIED,
                        this.placesAPI.PlacesServiceStatus.UNKNOWN_ERROR,
                    ];
                    if (status === this.placesAPI.PlacesServiceStatus.OK) {
                        placesService.getDetails(
                            {
                                placeId: results[0].place_id,
                                fields: ["geometry", "formatted_address"],
                            },
                            (place, status) => {
                                if (status === this.placesAPI.PlacesServiceStatus.OK) {
                                    this.gpsMapCache.set(coordinates, place);
                                    resolve(place);
                                } else if (GMAPS_CRITICAL_ERRORS.includes(status)) {
                                    log.logic(
                                        "GoogleMapsOptionPlugin getDetails critical error",
                                        () => ({
                                            status,
                                        }),
                                    );
                                    resolve({ error: status });
                                } else {
                                    resolve();
                                }
                            },
                        );
                    } else if (GMAPS_CRITICAL_ERRORS.includes(status)) {
                        log.logic(
                            "GoogleMapsOptionPlugin nearbySearch critical error",
                            () => ({
                                status,
                            }),
                        );
                        resolve({ error: status });
                    } else {
                        resolve();
                    }
                },
            );
        });
    }

    notifyGMapsError(editingElement) {
        if (!this.isGoogleMapsErrorBeingHandled) {
            this.isGoogleMapsErrorBeingHandled = true;
            log.logic("GoogleMapsOptionPlugin maps error: clear api key and restart");

            this.notification.add(
                _t(
                    "A Google Maps error occurred. Make sure to read the key configuration popup carefully.",
                ),
                { type: "danger", sticky: true },
            );
            this.orm
                .write("website", [this.websiteService.currentWebsite.id], {
                    google_maps_api_key: "",
                })
                .then(() => {
                    this.wasApiKeyInvalidated = true;
                    this.isGoogleMapsErrorBeingHandled = false;
                    this.dependencies.edit_interaction.restartInteractions(
                        editingElement,
                    );
                });
        }
    }
    shouldRefetchApiKey() {
        return this.wasApiKeyInvalidated || false;
    }
    shouldNotRefetchApiKey() {
        this.wasApiKeyInvalidated = false;
    }
}

export class ResetMapColorAction extends BuilderAction {
    static id = "resetMapColor";
    apply({ editingElement }) {
        log.pipeline("ResetMapColorAction apply");
        editingElement.dataset.mapColor = "";
    }
}
export class ShowDescriptionAction extends BuilderAction {
    static id = "showDescription";
    isApplied({ editingElement }) {
        return !!editingElement.querySelector(".description");
    }
    apply({ editingElement }) {
        const endRender = log.perf("ShowDescriptionAction render description");
        editingElement.append(renderToElement("html_builder.GoogleMapsDescription"));
        endRender();
    }
    clean({ editingElement }) {
        log.pipeline("ShowDescriptionAction clean");
        editingElement.querySelector(".description").remove();
    }
}

registry
    .category("website-plugins")
    .add(GoogleMapsOptionPlugin.id, GoogleMapsOptionPlugin);
