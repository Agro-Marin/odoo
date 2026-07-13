// @ts-check
/** @odoo-module native */

/** @module @web/services/scss_error_display - Detects SCSS compilation errors in stylesheets and shows a sticky notification */

import { browser } from "@web/core/browser/browser";
import { _t, translationIsReady } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getOrigin } from "@web/core/utils/urls";
import { user } from "@web/services/user";
export const scssErrorNotificationService = {
    dependencies: ["notification"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ notification: any }} services
     */
    start(env, { notification }) {
        const origin = getOrigin();
        // Iframe with src "about:blank" origin isn't a valid base URL.
        if (browser.location.origin === "null") {
            return;
        }
        // A failed SCSS compilation is an administrator/developer problem to
        // fix database-wide, so the sticky, un-actionable notification only
        // makes sense for users who can act on it: administrators, or anyone
        // in developer/debug mode. Bail early for everyone else so regular
        // users never get a "Style error" toast they can't resolve.
        if (!user.isAdmin && !odoo.debug) {
            return;
        }
        const assets = [...document.styleSheets].filter(
            (sheet) =>
                sheet.href?.includes("/web") &&
                sheet.href?.includes("/assets/") &&
                // CORS security rules don't allow reading content in JS
                new URL(sheet.href, browser.location.origin).origin === origin,
        );
        translationIsReady.then(() => {
            for (const asset of assets) {
                let cssRules;
                try {
                    // The filter above isn't enough: CORS can still block reading cssRules
                    // (e.g. same origin but http protocol), so never let this line crash.
                    // See opw 3746910.
                    cssRules = asset.cssRules;
                } catch {
                    continue;
                }
                const lastRule = cssRules?.[cssRules?.length - 1];
                if (
                    /** @type {CSSStyleRule} */ (lastRule)?.selectorText ===
                    "css_error_message"
                ) {
                    const message = _t(
                        "The style compilation failed. This is an administrator or developer error that must be fixed for the entire database before continuing working. See browser console or server logs for details.",
                    );
                    notification.add(message, {
                        title: _t("Style error"),
                        sticky: true,
                        type: "danger",
                    });
                    console.debug(
                        /** @type {CSSStyleRule} */ (lastRule).style.content
                            .replaceAll("\\a", "\n")
                            .replaceAll("\\*", "*")
                            .replaceAll(`\\"`, `"`),
                    );
                }
            }
        });
    },
};
registry.category("services").add("scss_error_display", scssErrorNotificationService);
