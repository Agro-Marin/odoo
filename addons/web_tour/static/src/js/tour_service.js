/** @odoo-module native */
import { Component, markup, validate, whenReady } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown";
import { loadBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { translationIsReady } from "@web/core/translation";
import { redirect } from "@web/core/utils/urls";
import { session } from "@web/session";
import { createPointerState } from "@web_tour/js/tour_pointer/tour_pointer_state";
import {
    TOUR_RECORDER_ACTIVE_LOCAL_STORAGE_KEY,
    tourRecorderState,
} from "@web_tour/js/tour_recorder/tour_recorder_state";
import { tourState } from "@web_tour/js/tour_state";
import { callWithUnloadCheck } from "@web_tour/js/utils/tour_utils";

import DOMPurify from "dompurify";

class OnboardingItem extends Component {
    static components = { DropdownItem };
    static template = "web_tour.OnboardingItem";
    static props = {
        toursEnabled: { type: Boolean },
        toggleItem: { type: Function },
    };
    setup() {}
}

const StepSchema = {
    id: { type: [String], optional: true },
    content: { type: [String, Object], optional: true }, //allow object(_t && markup)
    debugHelp: { type: String, optional: true },
    isActive: { type: Array, element: String, optional: true },
    run: { type: [String, Function, Boolean], optional: true },
    timeout: {
        optional: true,
        validate(value) {
            return value >= 0 && value <= 60000;
        },
    },
    tooltipPosition: {
        optional: true,
        validate(value) {
            return ["top", "bottom", "left", "right"].includes(value);
        },
    },
    trigger: { type: String },
    expectUnloadPage: { type: Boolean, optional: true },
    //ONLY IN DEBUG MODE
    pause: { type: Boolean, optional: true },
    break: { type: Boolean, optional: true },
};

const TourSchema = {
    name: { type: String, optional: true },
    steps: Function,
    // Tour-level default timeout applied to every step that does not define
    // its own (see ``step.timeout || this.timeout || 10000`` in
    // tour_automatic.js). Same bounds as the per-step ``timeout``.
    timeout: {
        optional: true,
        validate(value) {
            return value >= 0 && value <= 60000;
        },
    },
    url: { type: String, optional: true },
    wait_for: { type: [Function, Object], optional: true },
};

registry.category("web_tour.tours").addValidation(TourSchema);
const debugMenuRegistry = registry.category("debug").category("default");

// How long `whenTourIsRegistered` waits for a bundle to register a tour that
// localStorage says is mid-run.
//
// Not the 10 s a step spends looking for its trigger, which is what this was
// first set to: that budget is spent while the machine is otherwise idle,
// whereas this one is spent *during* a bundle evaluation, competing with it.
// `test_company_switch_access_error` under `?debug=assets` registers 361 ms
// after the read on an idle box -- and blew past 10 s on the same box at load
// average 5.6, turning a slow bundle into a hard test failure. It has to stay
// comfortably under the runner's own 60 s script timeout, so that a tour that
// genuinely never arrives is still reported here, with a reason, rather than
// as an anonymous timeout there.
const TOUR_REGISTRATION_TIMEOUT = 30000;

export const tourService = {
    // localization dependency to make sure translations used by tours are loaded
    dependencies: ["orm", "effect", "overlay", "localization"],
    start: async (env, { orm, effect, overlay }) => {
        await whenReady();
        let toursEnabled = session?.tour_enabled;
        const tourRegistry = registry.category("web_tour.tours");
        const pointer = createPointerState();
        pointer.stop = () => {};

        debugMenuRegistry.add("onboardingItem", () => ({
            type: "component",
            Component: OnboardingItem,
            props: {
                toursEnabled: toursEnabled || false,
                toggleItem: async () => {
                    tourState.clear();
                    toursEnabled = await orm.call("res.users", "switch_tour_enabled", [
                        !toursEnabled,
                    ]);
                    browser.location.reload();
                },
            },
            sequence: 500,
            section: "testing",
        }));

        function getTourFromRegistry(tourName) {
            if (!tourRegistry.contains(tourName)) {
                return;
            }
            const tour = tourRegistry.get(tourName);
            return {
                ...tour,
                steps: tour.steps(),
                name: tourName,
                wait_for: tour.wait_for || Promise.resolve(),
            };
        }

        async function getTourFromDB(tourName) {
            const tour = await orm.call("web_tour.tour", "get_tour_json_by_name", [
                tourName,
            ]);
            if (!tour) {
                throw new Error(`Tour '${tourName}' is not found in the database.`);
            }

            if (!tour.steps.length && tourRegistry.contains(tour.name)) {
                tour.steps = tourRegistry.get(tour.name).steps();
            }

            return tour;
        }

        function validateStep(step) {
            try {
                validate(step, StepSchema);
            } catch (error) {
                console.error(
                    `Error in schema for TourStep ${JSON.stringify(step, null, 4)}\n${
                        error.message
                    }`,
                );
            }
        }

        async function startTour(tourName, options = {}) {
            pointer.stop();
            const tourFromRegistry = getTourFromRegistry(tourName);

            if (!tourFromRegistry && !options.fromDB) {
                // Sometime tours are not loaded depending on the modules.
                // For example, point_of_sale do not load all tours assets.
                return;
            }

            const tour = options.fromDB
                ? { name: tourName, url: options.url }
                : tourFromRegistry;
            if (!session.is_public && !toursEnabled && options.mode === "manual") {
                toursEnabled = await orm.call("res.users", "switch_tour_enabled", [
                    !toursEnabled,
                ]);
            }

            let tourConfig = {
                delayToCheckUndeterminisms: 0,
                stepDelay: 0,
                keepWatchBrowser: false,
                mode: "auto",
                showPointerDuration: 0,
                debug: false,
                redirect: true,
            };

            tourConfig = Object.assign(tourConfig, options);
            tourState.setCurrentConfig(tourConfig);
            tourState.setCurrentTour(tour.name);
            tourState.setCurrentIndex(0);

            const willUnload = callWithUnloadCheck(() => {
                if (
                    tour.url &&
                    tourConfig.startUrl !== tour.url &&
                    tourConfig.redirect
                ) {
                    redirect(tour.url);
                }
            });
            if (!willUnload) {
                await resumeTour();
            }
        }

        /**
         * Resolve once `tourName` is in the tours registry, or after
         * `TOUR_REGISTRATION_TIMEOUT` if it never arrives.
         *
         * A tour is registered by whatever bundle defines it, and a bundle
         * served as ESM is evaluated *after* the services start -- so sampling
         * the registry once, which is what `resumeTour` used to do, is a race
         * by construction rather than a check.  Measured on
         * `test_company_switch_access_error` under `?debug=assets`: the
         * company switch reloads the page, `tourService.start` reads the
         * registry, and the tour lands in it **361 ms later**.  The one-shot
         * read lost that race on every run.
         *
         * `10000` is the same patience the step-level trigger wait already
         * spends (`tour_step.js`), and it is only ever spent when something is
         * actually wrong: a registered tour resolves this synchronously.
         */
        function whenTourIsRegistered(tourName, timeout = TOUR_REGISTRATION_TIMEOUT) {
            if (tourRegistry.contains(tourName)) {
                return Promise.resolve(true);
            }
            return new Promise((resolve) => {
                let timer;
                const onUpdate = (ev) => {
                    if (ev.detail.key !== tourName) {
                        return;
                    }
                    browser.clearTimeout(timer);
                    tourRegistry.removeEventListener("UPDATE", onUpdate);
                    resolve(true);
                };
                timer = browser.setTimeout(() => {
                    tourRegistry.removeEventListener("UPDATE", onUpdate);
                    resolve(false);
                }, timeout);
                tourRegistry.addEventListener("UPDATE", onUpdate);
            });
        }

        async function resumeTour() {
            const tourName = tourState.getCurrentTour();
            const tourConfig = tourState.getCurrentConfig();

            let tour;
            if (tourConfig.fromDB) {
                tour = await getTourFromDB(tourName);
            } else {
                // Synchronous first, and only wait when there is something to
                // wait for.  Awaiting unconditionally costs a microtask before
                // `startTour` does anything, and that is not free on a page
                // that is redirecting: the runner is inside
                // `Runtime.evaluate` on `odoo.startTour(...)`, and a
                // navigation landing in the widened window fails the whole
                // evaluate with "Inspected target navigated or closed".
                // `test_company_access_error_redirect` -- which exists to
                // redirect -- went from passing every run to failing three of
                // six on that one extra tick.
                tour = getTourFromRegistry(tourName);
                if (!tour) {
                    await whenTourIsRegistered(tourName);
                    tour = getTourFromRegistry(tourName);
                }
            }
            if (!tour) {
                if (tourConfig.mode !== "auto") {
                    // A manual tour can be legitimately absent from the page
                    // the user happens to be on: not every bundle carries
                    // every tour, which `startTour` says out loud a few lines
                    // up ("point_of_sale do not load all tours assets").
                    // Dropping the state here would end an onboarding tour
                    // that would have resumed fine on the next page, so it is
                    // left alone -- as it was before.
                    return;
                }
                // In `auto` mode there is a runner waiting on this tour, and
                // nothing is going to produce it.  Returning silently left
                // `current_tour` in localStorage naming a tour nobody can
                // produce, so every later page load re-entered this function
                // to return silently again -- and the runner could only report
                // the 60 s "Script timeout exceeded", which says nothing
                // about what happened.
                tourState.clear();
                browser.console.error(
                    `Tour "${tourName}" was resumed but is registered nowhere` +
                        ` (${tourConfig.fromDB ? "database" : "web_tour.tours registry"}).` +
                        " Its saved state has been dropped.",
                );
                return;
            }

            tour.steps.forEach((step) => validateStep(step));

            if (tourConfig.mode === "auto") {
                await loadBundle("web_tour.automatic", { css: false });
                const { TourAutomatic } =
                    await import("@web_tour/js/tour_automatic/tour_automatic");
                new TourAutomatic(tour).start();
            } else {
                await loadBundle("web_tour.interactive");
                const { TourPointer } =
                    await import("@web_tour/js/tour_pointer/tour_pointer");
                pointer.stop = overlay.add(
                    TourPointer,
                    {
                        pointerState: pointer.state,
                        bounce: !(
                            tourConfig.mode === "auto" && tourConfig.keepWatchBrowser
                        ),
                    },
                    {
                        sequence: 1100, // sequence based on bootstrap z-index values.
                    },
                );
                const { TourInteractive } =
                    await import("@web_tour/js/tour_interactive/tour_interactive");
                new TourInteractive(tour).start(env, pointer, async () => {
                    pointer.stop();
                    tourState.clear();
                    browser.console.log("tour succeeded");
                    let message =
                        tourConfig.rainbowManMessage || tour.rainbowManMessage;
                    if (message) {
                        message = DOMPurify.sanitize(tourConfig.rainbowManMessage);
                        effect.add({
                            type: "rainbow_man",
                            message: markup(message),
                        });
                    }

                    const nextTour = await orm.call("web_tour.tour", "consume", [
                        tour.name,
                    ]);
                    if (nextTour) {
                        startTour(nextTour.name, {
                            mode: "manual",
                            redirect: false,
                            rainbowManMessage: nextTour.rainbowManMessage,
                        });
                    }
                });
            }
        }

        async function tourRecorder() {
            await loadBundle("web_tour.recorder");
            const { TourRecorder } =
                await import("@web_tour/js/tour_recorder/tour_recorder");
            const remove = overlay.add(
                TourRecorder,
                {
                    onClose: () => {
                        remove();
                        browser.localStorage.removeItem(
                            TOUR_RECORDER_ACTIVE_LOCAL_STORAGE_KEY,
                        );
                        tourRecorderState.clear();
                    },
                },
                { sequence: 99999 },
            );
        }

        async function startTourRecorder() {
            if (!browser.localStorage.getItem(TOUR_RECORDER_ACTIVE_LOCAL_STORAGE_KEY)) {
                await tourRecorder();
            }
            browser.localStorage.setItem(TOUR_RECORDER_ACTIVE_LOCAL_STORAGE_KEY, "1");
        }

        if (!window.frameElement) {
            const paramsTourName = new URLSearchParams(browser.location.search).get(
                "tour",
            );
            if (paramsTourName) {
                startTour(paramsTourName, { mode: "manual", fromDB: true });
            }

            if (tourState.getCurrentTour()) {
                if (tourState.getCurrentConfig().mode === "auto" || toursEnabled) {
                    resumeTour();
                } else {
                    tourState.clear();
                }
            } else if (session.current_tour) {
                startTour(session.current_tour.name, {
                    mode: "manual",
                    redirect: false,
                    rainbowManMessage: session.current_tour.rainbowManMessage,
                });
            }

            if (
                browser.localStorage.getItem(TOUR_RECORDER_ACTIVE_LOCAL_STORAGE_KEY) &&
                !session.is_public
            ) {
                await tourRecorder();
            }
        }

        odoo.startTour = startTour;
        // Cheap "is the tour ready to start?" probe.  Test runners poll
        // this from outside (Runtime.evaluate inside ``try { ... } catch
        // {}``) so any throw silently becomes ``undefined`` — the test
        // then waits 60s and fails with "ready code was always falsy".
        //
        // Three things must be true before a tour can start:
        //   1. The tour is registered in ``web_tour.tours``.  Trivial
        //      registry membership check.
        //   2. The tour's optional ``wait_for`` predicate has resolved.
        //      Tours can declare async preconditions (e.g. wait for a
        //      bundle, a record fetch) and the test should not start
        //      until they fire.
        //   3. **Translations are loaded.**  Tour ``steps()`` functions
        //      routinely use ``_t(...)`` and ``markup(_t(...))``.  These
        //      eagerly throw ``"Cannot translate string: translations
        //      have not been loaded"`` if called before
        //      ``translationIsReady`` resolves.  ``getTourFromRegistry``
        //      (called by both ``isTourReady`` formerly and ``startTour``
        //      always) evaluates ``steps()`` eagerly — so without
        //      gating on translations, the test framework would either
        //      silently swallow the throw (legacy behavior, "ready always
        //      falsy") or, worse, see ``isTourReady`` return true, fire
        //      ``startTour``, and crash inside ``getTourFromRegistry``
        //      with a fatal browser error.  Both have been observed in
        //      the test_main_flows tour suite during fresh-DB cold
        //      starts where the localization service is still warming
        //      up after Owl mounts.
        odoo.isTourReady = (tourName) => {
            if (!tourRegistry.contains(tourName)) {
                return false;
            }
            const tour = tourRegistry.get(tourName);
            return Promise.all([
                translationIsReady,
                tour.wait_for || Promise.resolve(),
                // The automatic runtime, fetched here rather than on the far
                // side of "ready".
                //
                // The only caller of this probe is the test runner, which
                // starts the tour in `auto` mode the instant it answers true --
                // and `resumeTour` then has to fetch `web_tour.automatic`
                // before a single step can run. On a page that unloads while it
                // is still loading, that fetch races the teardown. The runner
                // is inside `Runtime.evaluate` on `odoo.startTour(...)` with
                // `awaitPromise`, so losing the race does not merely delay the
                // tour: the promise never settles and CDP kills the evaluate
                // with "Inspected target navigated or closed", which says
                // nothing about what happened.
                //
                // `test_company_access_error_redirect` is that page by
                // construction -- it opens a record the active company cannot
                // see, and the client switches company and reloads. Its tour
                // already declares the consequence on its first step
                // (`expectUnloadPage`), and that declaration is correct and
                // sufficient: instrumented, the runs that pass are exactly the
                // ones where the bundle arrives in time for that step to run
                // and bank the reload, and the runs that fail are the ones
                // where it does not. What was missing was never the
                // declaration -- it was having the runtime that honours it
                // before the clock starts.
                loadBundle("web_tour.automatic", { css: false }),
            ]).then(() => true);
        };

        return {
            startTour,
            startTourRecorder,
        };
    },
};

registry.category("services").add("tour_service", tourService);
