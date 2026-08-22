// @ts-check
/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useColorScheme } from "@web/core/color_scheme";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { colorSchemeService } from "@web/webclient/color_scheme/color_scheme_service";

export class DarkModeToggle extends Component {
    static template = "web.DarkModeToggle";
    static props = {};

    /** @type {ReturnType<typeof useColorScheme>} */
    colorScheme;

    setup() {
        this.colorScheme = useColorScheme();
    }

    /** @returns {string} */
    get label() {
        return this.colorScheme.isDark
            ? _t("Switch to light mode")
            : _t("Switch to dark mode");
    }

    async toggle() {
        const newScheme = this.colorScheme.isDark ? "light" : "dark";
        await user.setUserSettings("color_scheme", newScheme);
        colorSchemeService.reload();
    }
}

const darkModeToggle = {
    Component: DarkModeToggle,
};

registry
    .category("systray")
    .add("web.dark_mode_toggle", darkModeToggle, { sequence: 5 });
