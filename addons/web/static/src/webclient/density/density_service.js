// @ts-check
/** @odoo-module native */

/** @module @web/webclient/density/density_service */

import { reactive } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

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

/**
 * The `density` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * Only `state` is reactive here, not the service — consumers read
 * `service.state.density` or `service.current` — so this needs no
 * `reactive(new …)` wrapper, unlike `pwa` and `ui` whose whole surface is read
 * from templates.
 */
export class DensityService {
    constructor() {
        const userDensity = user.settings?.density;
        this.state = reactive({
            density: DENSITIES.includes(userDensity) ? userDensity : "default",
        });

        if (cookie.get("content_density") !== this.state.density) {
            cookie.set("content_density", this.state.density);
        }
        applyDensityClass(this.state.density);
    }

    get current() {
        return this.state.density;
    }

    /** @param {string} density */
    _apply(density) {
        this.state.density = density;
        applyDensityClass(density);
        cookie.set("content_density", density);
    }

    /** @param {string} density */
    async set(density) {
        if (!DENSITIES.includes(density)) {
            return;
        }
        const previous = this.state.density;
        this._apply(density);
        try {
            await user.setUserSettings("density", density);
        } catch (error) {
            this._apply(previous);
            console.warn("Could not persist the content density", error);
        }
    }

    async cycle() {
        await this.set(nextDensity(this.state.density));
    }
}

export const densityService = {
    /** @returns {DensityService} */
    start() {
        return new DensityService();
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
