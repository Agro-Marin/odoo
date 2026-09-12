/** @odoo-module native */

import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame } from "@odoo/hoot-dom";
import { Component, xml } from "@odoo/owl";
import {
    clearRegistry,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { Macro } from "@web/core/utils/macro";
import { session } from "@web/session";
import { tourState } from "@web_tour/js/tour_state";

describe.current.tags("desktop");

const tourRegistry = registry.category("web_tour.tours");
let macro;

class Root extends Component {
    static components = {};
    static template = xml`<t><button class="button0">Button 0</button></t>`;
    static props = ["*"];
}

async function pump(times = 6) {
    for (let i = 0; i < times; i++) {
        await animationFrame();
        await advanceTime(265);
    }
}

beforeEach(() => {
    clearRegistry(tourRegistry);
    tourState.clear();
    patchWithCleanup(Macro.prototype, {
        start() {
            super.start(...arguments);
            macro = this;
        },
    });
});

afterEach(() => {
    macro?.stop();
    macro = undefined;
    tourState.clear();
});

describe("resuming a tour the registry does not have yet", () => {
    test("a tour registered after the service started still resumes", async () => {
        tourState.setCurrentTour("late_tour");
        tourState.setCurrentConfig({ mode: "auto", stepDelay: 0 });
        tourState.setCurrentIndex(0);

        await mountWithCleanup(Root);
        expect(tourRegistry.contains("late_tour")).toBe(false);

        tourRegistry.add("late_tour", {
            steps: () => [
                {
                    trigger: ".button0",
                    run() {
                        expect.step("late tour ran");
                    },
                },
            ],
        });
        await pump();
        expect.verifySteps(["late tour ran"]);
    });

    test("a manual tour absent from this page keeps its state and stays quiet", async () => {
        patchWithCleanup(browser.console, {
            error: (msg) => expect.step(`error: ${msg}`),
        });
        patchWithCleanup(session, { tour_enabled: true });
        tourState.setCurrentTour("elsewhere_tour");
        tourState.setCurrentConfig({ mode: "manual", stepDelay: 0 });

        await mountWithCleanup(Root);
        await advanceTime(31000);
        await animationFrame();

        expect(tourState.getCurrentTour()).toBe("elsewhere_tour");
        expect.verifySteps([]);
    });

    test("a tour nobody can produce is reported and its state dropped", async () => {
        patchWithCleanup(browser.console, {
            error: (msg) => expect.step(`error: ${msg}`),
        });
        tourState.setCurrentTour("no_such_tour");
        tourState.setCurrentConfig({ mode: "auto", stepDelay: 0 });

        await mountWithCleanup(Root);
        await advanceTime(31000);
        await animationFrame();

        expect(tourState.getCurrentTour()).toBe(null);
        expect.verifySteps([
            'error: Tour "no_such_tour" was resumed but is registered nowhere' +
                " (web_tour.tours registry). Its saved state has been dropped.",
        ]);
    });
});
