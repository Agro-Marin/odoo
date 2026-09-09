/** @odoo-module native */
import { browser } from "@web/core/browser/browser";

const CURRENT_TOUR_LOCAL_STORAGE = "current_tour";
const CURRENT_TOUR_CONFIG_LOCAL_STORAGE = "current_tour.config";
const CURRENT_TOUR_INDEX_LOCAL_STORAGE = "current_tour.index";
const CURRENT_TOUR_ON_ERROR_LOCAL_STORAGE = "current_tour.on_error";

export const tourState = {
    getCurrentTour() {
        return browser.localStorage.getItem(CURRENT_TOUR_LOCAL_STORAGE);
    },
    setCurrentTour(tourName) {
        browser.localStorage.setItem(CURRENT_TOUR_LOCAL_STORAGE, tourName);
    },
    getCurrentIndex() {
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
