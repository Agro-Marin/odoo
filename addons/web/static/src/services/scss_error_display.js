// @ts-check
/** @odoo-module native */

/** @module @web/services/scss_error_display */

import { browser } from "@web/core/browser/browser";
import { _t, translationIsReady } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getOrigin } from "@web/core/utils/urls";
import { user } from "@web/services/user";

/**
 * @returns {boolean}
 */
export function canActOnScssErrors() {
    return Boolean(user.isAdmin || odoo.debug);
}

export const scssErrorNotificationService = {
    dependencies: ["notification"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ notification: any }} services
     */
    start(env, { notification }) {
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
        let destroyed = false;
        translationIsReady.then(() => {
            if (destroyed) {
                return;
            }
            let notified = false;
            for (const asset of assets) {
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
                    notification.add(
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
        });

        return {
            destroy() {
                destroyed = true;
            },
        };
    },
};
registry.category("services").add("scss_error_display", scssErrorNotificationService);
