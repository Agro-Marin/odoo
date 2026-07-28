// @ts-check
/** @odoo-module native */

/** @module @web/services/scss_error_display - Detects SCSS compilation errors in stylesheets and shows a sticky notification */

import { browser } from "@web/core/browser/browser";
import { _t, translationIsReady } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getOrigin } from "@web/core/utils/urls";
import { user } from "@web/services/user";

/**
 * Whether the current user is someone a style-compilation error is actionable
 * for.
 *
 * A failed SCSS compilation is an administrator/developer problem to fix
 * database-wide, so the sticky, un-actionable notification only makes sense for
 * people who can act on it. Exported as a named policy rather than left inline
 * in {@link scssErrorNotificationService}: the service around it can only be
 * exercised through a browser tour (it scrapes `document.styleSheets`), so an
 * inline check was in practice untestable — and it silently invalidated the
 * frontend tour, which runs as the public user and had asserted the toast
 * appeared for everyone.
 *
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
        // `translationIsReady` is a module-scoped promise that may already be
        // long-settled or may settle after this env is gone. Without the guard,
        // a torn-down env still pushes a sticky danger toast into a
        // notification service that is no longer displayed anywhere.
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
                // One toast, however many bundles failed: the message is
                // identical and un-actionable per-bundle, so N failing assets
                // used to stack N sticky danger notifications over the UI.
                // The console dump still runs per asset — that IS per-bundle
                // diagnostic detail.
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
