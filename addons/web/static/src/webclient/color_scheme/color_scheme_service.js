// @ts-check
/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { colorScheme } from "@web/core/color_scheme";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

const serviceRegistry = registry.category("services");

const DARK_SCHEME_QUERY = "(prefers-color-scheme:dark)";

class ColorSchemeService {
    constructor() {
        this.systemScheme = browser.matchMedia(DARK_SCHEME_QUERY);
        const stored = user.settings.color_scheme;
        colorScheme.publish(
            stored === "light" || stored === "dark" ? stored : this.systemColorScheme,
        );
        this._onSystemSchemeChange = () => this.onSystemSchemeChange();
        this.systemScheme.addEventListener("change", this._onSystemSchemeChange);
    }

    onSystemSchemeChange() {
        if (!["light", "dark"].includes(user.settings.color_scheme)) {
            colorScheme.publish(this.systemColorScheme);
        }
    }

    get systemColorScheme() {
        return this.systemScheme.matches ? "dark" : "light";
    }

    get currentColorScheme() {
        return colorScheme.current;
    }

    get userColorScheme() {
        return user.settings.color_scheme;
    }

    destroy() {
        this.systemScheme.removeEventListener?.("change", this._onSystemSchemeChange);
    }
}

export const colorSchemeService = {
    /** @returns {Promise<ColorSchemeService>} */
    async start() {
        return new ColorSchemeService();
    },
    reload() {
        browser.location.reload();
    },
};
serviceRegistry.add("color_scheme", colorSchemeService);
