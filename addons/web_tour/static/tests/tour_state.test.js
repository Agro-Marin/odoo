/** @odoo-module native */

import { describe, expect, test } from "@odoo/hoot";
import { browser } from "@web/core/browser/browser";
import { tourState } from "@web_tour/js/tour_state";

describe.current.tags("headless");

describe("defaults for an unset key", () => {
    test("the index reads as the first step, not NaN", () => {
        browser.localStorage.removeItem("current_tour.index");
        expect(tourState.getCurrentIndex()).toBe(0);
    });

    test("a stored index still reads back", () => {
        tourState.setCurrentIndex(4);
        expect(tourState.getCurrentIndex()).toBe(4);
        tourState.clear();
        expect(tourState.getCurrentIndex()).toBe(0);
    });

    test("the config reads as an empty object, not null", () => {
        browser.localStorage.removeItem("current_tour.config");
        expect(tourState.getCurrentConfig()).toEqual({});
    });

    test("a stored config still reads back", () => {
        tourState.setCurrentConfig({ mode: "auto", stepDelay: 10 });
        expect(tourState.getCurrentConfig()).toEqual({ mode: "auto", stepDelay: 10 });
        tourState.clear();
        expect(tourState.getCurrentConfig()).toEqual({});
    });
});
