// @ts-check
/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useColorScheme } from "@web/core/color_scheme";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { colorSchemeService } from "@web/webclient/color_scheme/color_scheme_service";

/**
 * Systray toggle for switching between light and dark color schemes.
 *
 * Persists the preference via res.users.settings (same mechanism as
 * Settings > Preferences > Theme) and reloads to swap CSS bundles.
 */
export class DarkModeToggle extends Component {
    static template = "web.DarkModeToggle";
    static props = {};

    /** @type {ReturnType<typeof useColorScheme>} */
    colorScheme;

    setup() {
        // Subscribed, not sampled: a `system` user is served both stylesheets
        // behind prefers-color-scheme, so the OS switching theme repaints the
        // page and republishes the scheme without this component being asked.
        // Read once at setup, the button offered to switch to the mode already
        // on screen.
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
        // Persist to database so color_scheme_service doesn't overwrite on
        // reload. Through `user`, which issues this very call and then folds
        // the server's answer back into `user.settings` — a hand-rolled copy
        // left that stale, so any reader before the reload saw the old scheme.
        await user.setUserSettings("color_scheme", newScheme);
        // The cookie is not set here. It is the server's answer to the setting
        // just saved, and every way this page can be re-served goes through
        // `web_client`, which sets it: `location.reload()` directly, and
        // website_enterprise's `/@/...` by redirecting to an `/odoo/...` URL.
        // Writing it too would make this a third writer of a value it does not
        // decide, and one that has to stay in step with `ir_http.color_scheme`.
        //
        // Through the service, not browser.location directly: it owns how the
        // page is re-served, and website_enterprise overrides it to re-enter
        // the builder rather than reload the preview out from under itself.
        colorSchemeService.reload();
    }
}

export const darkModeToggle = {
    Component: DarkModeToggle,
};

registry
    .category("systray")
    .add("web.dark_mode_toggle", darkModeToggle, { sequence: 5 });
