// @ts-check
/** @odoo-module native */

/** @module @web/webclient/density/density_service */

import { reactive } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { registry } from "@web/core/registry";
import { user } from "@web/services/user";

/**
 * @type {string[]}
 */
export const DENSITIES = ["default", "compact", "condensed"];

/**
 * @type {Record<string, string>}
 */
const DENSITY_CLASSES = {
    compact: "o-density-compact",
    condensed: "o-density-condensed",
};

/**
 * @param {string} density
 * @returns {string}
 */
export function nextDensity(density) {
    const index = DENSITIES.indexOf(density);
    return DENSITIES[(index + 1) % DENSITIES.length];
}

export const densityService = {
    /**
     * @returns {{ state: { density: string }, current: string, set: (density: string) => Promise<void>, cycle: () => Promise<void> }}
     */
    start() {
        const userDensity = user.settings?.density;
        const state = reactive({
            density: DENSITIES.includes(userDensity) ? userDensity : "default",
        });

        function apply(/** @type {string} */ density) {
            state.density = density;
            applyDensityClass(density);
            cookie.set("content_density", density);
        }

        if (cookie.get("content_density") !== state.density) {
            cookie.set("content_density", state.density);
        }

        applyDensityClass(state.density);

        return {
            state,
            get current() {
                return state.density;
            },
            async set(density) {
                if (!DENSITIES.includes(density)) {
                    return;
                }
                const previous = state.density;
                apply(density);
                try {
                    await user.setUserSettings("density", density);
                } catch (error) {
                    apply(previous);
                    console.warn("Could not persist the content density", error);
                }
            },
            async cycle() {
                await this.set(nextDensity(state.density));
            },
        };
    },
};

/**
 * @param {string} density
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
