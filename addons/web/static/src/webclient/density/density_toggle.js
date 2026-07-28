// @ts-check
/** @odoo-module native */

/** @module @web/webclient/density/density_toggle - Systray toggle that cycles through content density modes (default/compact/condensed) */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { nextDensity } from "./density_service.js";

/**
 * Presentation only. The cycle order is NOT repeated here — it belongs to the
 * service ({@link nextDensity}); this table previously carried a ``next:``
 * chain that duplicated it and could drift out of step with the service's own
 * ordering.
 */
const DENSITY_META = {
    default: {
        icon: "fa-solid fa-up-right-and-down-left-from-center",
        label: _t("Default"),
    },
    compact: {
        icon: "fa-solid fa-down-left-and-up-right-to-center",
        label: _t("Compact"),
    },
    condensed: { icon: "fa-solid fa-bars", label: _t("Condensed") },
};

/**
 * Systray toggle that cycles through content density modes.
 *
 * Cycles: default (cozy) → compact → condensed → default.
 * No page reload — CSS class toggle is instant.
 */
export class DensityToggle extends Component {
    static template = "web.DensityToggle";
    static props = {};

    setup() {
        this.densityService = /** @type {any} */ (useService("density"));
        // Subscribing to the service's own reactive state is what makes the
        // icon and tooltip track a density set from anywhere, not just from
        // this component's toggle().
        this.state = useState(this.densityService.state);
    }

    /** @returns {string} the current density, always one of DENSITY_META's keys */
    get density() {
        return this.state.density in DENSITY_META ? this.state.density : "default";
    }

    /** @returns {string} Font Awesome icon class for the current density. */
    get icon() {
        return DENSITY_META[this.density].icon;
    }

    /** @returns {string} Tooltip text describing current density and next on click. */
    get title() {
        return _t("%(current)s density (click for %(next)s)", {
            current: DENSITY_META[this.density].label,
            next: DENSITY_META[nextDensity(this.density)].label,
        });
    }

    /** Cycle to the next density mode. */
    async toggle() {
        await this.densityService.cycle();
    }
}

export const densityToggle = { Component: DensityToggle };

registry.category("systray").add("web.density_toggle", densityToggle, { sequence: 6 });
