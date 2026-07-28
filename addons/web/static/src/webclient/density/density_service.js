// @ts-check
/** @odoo-module native */

/** @module @web/webclient/density/density_service - Service managing content density (default/compact/condensed) via body CSS class toggles */

import { reactive } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { registry } from "@web/core/registry";
import { user } from "@web/services/user";

/**
 * The densities, in cycle order — ``cycle()`` steps to the next entry and
 * wraps. This array is the ONLY place the order lives: it used to be spelled
 * out three times (this list, a re-declared ``order`` inside ``cycle()``, and
 * the ``next:`` chain of ``DENSITY_META`` in ``density_toggle.js``), so adding
 * a density meant editing three lists in two files and any one of them could
 * silently disagree.
 *
 * @type {string[]}
 */
export const DENSITIES = ["default", "compact", "condensed"];

/**
 * Body class per density. ``default`` deliberately has no entry: it is the
 * absence of an override, not a class of its own.
 * @type {Record<string, string>}
 */
const DENSITY_CLASSES = {
    compact: "o-density-compact",
    condensed: "o-density-condensed",
};

/** @param {string} density @returns {string} the density that follows it in the cycle */
export function nextDensity(density) {
    const index = DENSITIES.indexOf(density);
    return DENSITIES[(index + 1) % DENSITIES.length];
}

/**
 * Manage content density (default/compact/condensed) via a body class.
 *
 * Unlike dark mode (which swaps CSS bundles and reloads), density only
 * toggles a body class that overrides CSS custom properties — so switching
 * is instant with no page reload.
 */
export const densityService = {
    /** @returns {{ current: string, set: (density: string) => Promise<void>, cycle: () => Promise<void> }} */
    start() {
        const userDensity = user.settings?.density;
        /**
         * Reactive so every consumer re-renders on a change, wherever it came
         * from. ``DensityToggle`` used to mirror ``current`` into its own
         * ``useState`` and re-read it only inside its own ``toggle()``, so a
         * density set by anything else left the systray icon and tooltip
         * showing the previous mode until the next unrelated render.
         */
        const state = reactive({
            density: DENSITIES.includes(userDensity) ? userDensity : "default",
        });

        if (cookie.get("content_density") !== state.density) {
            cookie.set("content_density", state.density);
        }

        applyDensityClass(state.density);

        return {
            /**
             * The reactive density holder. Exposed (rather than only the
             * ``current`` getter) because a getter reads the reactive from a
             * closure, which subscribes nothing: a component must be handed
             * the reactive object itself to ``useState`` for its render to be
             * re-run on a change.
             */
            state,
            get current() {
                return state.density;
            },
            /** Switch to the given density without page reload. */
            async set(density) {
                if (!DENSITIES.includes(density)) {
                    return;
                }
                state.density = density;
                applyDensityClass(density);
                cookie.set("content_density", density);
                await user.setUserSettings("density", density);
            },
            /** Cycle: default → compact → condensed → default. */
            async cycle() {
                await this.set(nextDensity(state.density));
            },
        };
    },
};

/**
 * Toggle the appropriate body CSS class for the given density.
 * @param {string} density - One of "default", "compact", or "condensed"
 */
function applyDensityClass(density) {
    const { classList } = document.body;
    for (const cls of Object.values(DENSITY_CLASSES)) {
        classList.remove(cls);
    }
    if (density in DENSITY_CLASSES) {
        classList.add(DENSITY_CLASSES[density]);
    }
}

registry.category("services").add("density", densityService);
