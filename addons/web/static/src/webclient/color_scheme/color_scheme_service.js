// @ts-check
/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { colorScheme } from "@web/core/color_scheme";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

const serviceRegistry = registry.category("services");

export function systemColorScheme() {
    return browser.matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light";
}

function currentColorScheme() {
    return colorScheme.current;
}

// This service decides *which* scheme is in effect; `colorScheme` in @web/core
// carries it, and is the one application code should read — it lives below
// webclient/, so anything can reach it.

/**
 * The `color_scheme` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * **`reload()` stays on the service object below**, not on this class:
 * `dark_mode_toggle.js` imports `colorSchemeService` directly and calls it, so
 * it is a live facade method in the same sense as `fileUploadService.createXhr`.
 *
 * The system-scheme listener goes through a stored wrapper so
 * `removeEventListener` keeps its reference while the handler resolves through
 * the prototype (hazard 2).
 */
export class ColorSchemeService {
    constructor() {
        const stored = user.settings.color_scheme;
        const newColorScheme =
            stored === "light" || stored === "dark" ? stored : systemColorScheme();
        // A backstop, not the mechanism. webclient_bootstrap resolves the
        // cookie inline before any bundle runs, and the server sets it outright
        // for an explicit preference, so this only matters where the webclient
        // boots from some other template. Nothing reloads: the stylesheet is
        // already right — both bundles ship behind prefers-color-scheme — and
        // the cookie was settled before the first reader could see it.
        //
        // Published unconditionally rather than only when it differs. The two
        // carriers can disagree with each other, not just with the answer —
        // a template that sets the cookie and not the attribute leaves the
        // token layer on the wrong scheme, and comparing against one of them
        // cannot see that. Writing both says what is true either way, and
        // there is nothing to skip: it is one cookie the server sets anyway.
        colorScheme.publish(newColorScheme);
        // A `system` user is served both stylesheets behind
        // prefers-color-scheme, so the OS switching theme repaints the page
        // immediately — while the cookie, and every reader of it, would keep
        // answering with the scheme that was in effect at boot. The stylesheet
        // needs nothing from us; the readers do. Whatever renders after this
        // gets the scheme actually on screen instead of the stale one, and
        // whatever is already mounted re-renders through `useColorScheme`.
        this.systemScheme = browser.matchMedia("(prefers-color-scheme:dark)");
        this._onSystemSchemeChange = () => this.onSystemSchemeChange();
        this.systemScheme.addEventListener("change", this._onSystemSchemeChange);
    }

    onSystemSchemeChange() {
        if (!["light", "dark"].includes(user.settings.color_scheme)) {
            colorScheme.publish(systemColorScheme());
        }
    }

    get systemColorScheme() {
        return systemColorScheme();
    }

    get currentColorScheme() {
        return currentColorScheme();
    }

    get userColorScheme() {
        return user.settings.color_scheme;
    }

    // `colorScheme` is one module-level carrier shared by every env, so
    // a listener left behind does not merely leak: it goes on
    // publishing into the live scheme on behalf of an env that is gone.
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
