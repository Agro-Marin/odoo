// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

import { nextDensity } from "./density_service.js";

/** @type {Record<string, { icon: string, label: any }>} */
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

export class DensityToggle extends Component {
    static template = "web.DensityToggle";
    static props = {};

    setup() {
        this.densityService = /** @type {any} */ (useService("density"));
        this.state = useState(this.densityService.state);
    }

    /** @returns {string} */
    get density() {
        return this.state.density in DENSITY_META ? this.state.density : "default";
    }

    /** @returns {string} */
    get icon() {
        return DENSITY_META[this.density].icon;
    }

    /** @returns {string} */
    get title() {
        return _t("%(current)s density (click for %(next)s)", {
            current: DENSITY_META[this.density].label,
            next: DENSITY_META[nextDensity(this.density)].label,
        });
    }

    async toggle() {
        await this.densityService.cycle();
    }
}

const densityToggle = { Component: DensityToggle };

registry.category("systray").add("web.density_toggle", densityToggle, { sequence: 6 });
