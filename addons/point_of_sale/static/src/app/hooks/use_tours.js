/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";
import { tourState } from "@web_tour/js/tour_state";
const log = makeLogger("pos.tours");

import { TourSelectorPopup } from "../components/tour_selector_popup/tour_selector_popup.js";
import { makeAwaitable } from "../utils/make_awaitable_dialog.js";
export default function useTours() {
    const tour = useService("tour_service");
    const dialog = useService("dialog");
    const states = {
        selectedTours: new Set(),
        running: false,
        index: 0,
    };

    let fakeTourInterval = null;

    tourState.clear();

    const toggle = async () => {
        states.index = 0;
        states.running = !states.running;
        clearInterval(fakeTourInterval);
        log.lifecycle("toggle", () => ({ running: states.running }));

        if (!states.running) {
            tourState.clear();
            return;
        }

        const tours = await makeAwaitable(dialog, TourSelectorPopup, {});
        if (!tours || !tours.length) {
            tourState.clear();
            states.running = false;
            return;
        }

        states.selectedTours = tours;
        log.lifecycle("tours selected", () => ({ tours }));
        fakeTourInterval = setInterval(() => {
            const state = tourState.getCurrentTour();
            if (!state) {
                runTour();
            }
        }, 500);
    };

    const runTour = async () => {
        try {
            if (states.index >= states.selectedTours.length) {
                states.index = 0;
            }
            const endTour = log.perf(`tour ${states.selectedTours[states.index]}`);
            await tour.startTour(states.selectedTours[states.index], {
                throw: false,
            });
            endTour({ index: states.index });

            states.index++;
        } catch (error) {
            console.warn("Error in tour", error);
        }
    };

    return { toggle };
}
