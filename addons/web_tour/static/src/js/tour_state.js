/** @odoo-module native */
import { browser } from "@web/core/browser/browser";

const CURRENT_TOUR_LOCAL_STORAGE = "current_tour";
const CURRENT_TOUR_CONFIG_LOCAL_STORAGE = "current_tour.config";
const CURRENT_TOUR_INDEX_LOCAL_STORAGE = "current_tour.index";
const CURRENT_TOUR_ON_ERROR_LOCAL_STORAGE = "current_tour.on_error";

/**
 * Wrapper around localStorage for persistence of the running tours.
 * Useful for resuming running tours when the page refreshed.
 */
export const tourState = {
    getCurrentTour() {
        return browser.localStorage.getItem(CURRENT_TOUR_LOCAL_STORAGE);
    },
    setCurrentTour(tourName) {
        browser.localStorage.setItem(CURRENT_TOUR_LOCAL_STORAGE, tourName);
    },
    getCurrentIndex() {
        // `Storage.getItem` takes ONE argument.  The "0" that used to sit here
        // was accepted by the parser and dropped by the API, so an absent key
        // reached `parseInt(null, 10)` and this returned NaN.
        //
        // NaN is silent everywhere it lands.  `TourAutomatic.start` keeps the
        // steps with `step.index >= this.currentIndex`, and every comparison
        // against NaN is false -- a tour resumed without a stored index ran
        // zero steps and reported success.  `describeWhereIFailed` loops from
        // NaN to NaN and prints nothing.  `TourInteractive.backward` walks
        // `while (tempIndex >= 0)` and stops immediately.  The only visible
        // trace was the "index NaN of 2" in a tour's own error line.
        const index = browser.localStorage.getItem(CURRENT_TOUR_INDEX_LOCAL_STORAGE);
        return index === null ? 0 : parseInt(index, 10);
    },
    setCurrentIndex(index) {
        browser.localStorage.setItem(
            CURRENT_TOUR_INDEX_LOCAL_STORAGE,
            index.toString(),
        );
    },
    getCurrentConfig() {
        // Same dropped default as `getCurrentIndex`: without a stored config
        // this parsed the string "null" and answered `null`, so every caller
        // reading a key off it -- `tour_service`'s `getCurrentConfig().mode`,
        // `TourStepAutomatic`'s `this.tourConfig` -- was one absent key away
        // from a TypeError.
        const config = browser.localStorage.getItem(CURRENT_TOUR_CONFIG_LOCAL_STORAGE);
        return JSON.parse(config ?? "{}");
    },
    setCurrentConfig(config) {
        config = JSON.stringify(config);
        browser.localStorage.setItem(CURRENT_TOUR_CONFIG_LOCAL_STORAGE, config);
    },
    getCurrentTourOnError() {
        return browser.localStorage.getItem(CURRENT_TOUR_ON_ERROR_LOCAL_STORAGE);
    },
    setCurrentTourOnError() {
        browser.localStorage.setItem(CURRENT_TOUR_ON_ERROR_LOCAL_STORAGE, "1");
    },
    clear() {
        browser.localStorage.removeItem(CURRENT_TOUR_ON_ERROR_LOCAL_STORAGE);
        browser.localStorage.removeItem(CURRENT_TOUR_CONFIG_LOCAL_STORAGE);
        browser.localStorage.removeItem(CURRENT_TOUR_INDEX_LOCAL_STORAGE);
        browser.localStorage.removeItem(CURRENT_TOUR_LOCAL_STORAGE);
    },
};
