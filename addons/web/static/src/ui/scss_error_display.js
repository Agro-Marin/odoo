// @ts-check
/** @odoo-module native */

/** @module @web/ui/scss_error_display */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t, translationIsReady } from "@web/core/translation";
import { user } from "@web/core/user";
import { getOrigin } from "@web/core/utils/urls";

/**
 * @returns {boolean}
 */
export function canActOnScssErrors() {
    return Boolean(user.isAdmin || odoo.debug);
}

/**
 * The `scss_error_display` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * **The three guards stay in `start()`**, as in `web_vitals` and `profiling`:
 * they decide whether there is a service at all — a null origin, a browser that
 * cannot read cross-origin rules, and no matching stylesheets all mean nothing
 * to watch — and a constructor cannot decline to construct.
 */
export class ScssErrorDisplayService {
    /**
     * @param {{ notification: any }} services
     * @param {CSSStyleSheet[]} assets
     */
    constructor({ notification }, assets) {
        this.notification = notification;
        this.assets = assets;
        this.destroyed = false;
        translationIsReady.then(() => this.report());
    }

    /**
     * Runs once translations are loaded, so the notification is translated.
     * Silent if the service was destroyed while waiting.
     */
    report() {
        if (this.destroyed) {
            return;
        }
        let notified = false;
        for (const asset of this.assets) {
            let cssRules;
            try {
                cssRules = asset.cssRules;
            } catch {
                continue;
            }
            const lastRule = cssRules?.[cssRules?.length - 1];
            if (
                /** @type {CSSStyleRule} */ (lastRule)?.selectorText !==
                "css_error_message"
            ) {
                continue;
            }
            if (!notified) {
                notified = true;
                this.notification.add(
                    _t(
                        "The style compilation failed. This is an administrator or developer error that must be fixed for the entire database before continuing working. See browser console or server logs for details.",
                    ),
                    {
                        title: _t("Style error"),
                        sticky: true,
                        type: "danger",
                    },
                );
            }
            // eslint-disable-next-line no-console -- dumps the failing SCSS rule for the developer to diagnose
            console.debug(
                /** @type {CSSStyleRule} */ (lastRule).style.content
                    .replaceAll("\\a", "\n")
                    .replaceAll("\\*", "*")
                    .replaceAll(`\\"`, `"`),
            );
        }
    }

    destroy() {
        this.destroyed = true;
    }
}

export const scssErrorNotificationService = {
    dependencies: ["notification"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ notification: any }} services
     */
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ notification: any }} services
     * @returns {ScssErrorDisplayService | undefined}
     */
    start(env, services) {
        const origin = getOrigin();
        if (browser.location.origin === "null") {
            return;
        }
        if (!canActOnScssErrors()) {
            return;
        }
        const assets = [...document.styleSheets].filter(
            (sheet) =>
                sheet.href?.includes("/web") &&
                sheet.href?.includes("/assets/") &&
                new URL(sheet.href, browser.location.origin).origin === origin,
        );
        return new ScssErrorDisplayService(services, assets);
    },
};
registry.category("services").add("scss_error_display", scssErrorNotificationService);
