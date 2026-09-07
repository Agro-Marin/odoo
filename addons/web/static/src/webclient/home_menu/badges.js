// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

// A provider answers `provide(env, apps)` with counts by app xmlid, sync or not.
registry.category("home_menu_badges").addValidation({ provide: Function });

/**
 * Every `home_menu_badges` provider answers with counts by app xmlid; a tile
 * shows their sum. A provider that fails costs its own counts only.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {{ xmlid?: string }[]} apps
 * @returns {Promise<Record<string, number>>}
 */
export async function loadHomeMenuBadges(env, apps) {
    const providers = registry.category("home_menu_badges").getAll();
    /** @type {Record<string, number>} */
    const badges = {};
    if (!providers.length) {
        return badges;
    }
    const settled = await Promise.allSettled(
        providers.map((provider) => provider.provide(env, apps)),
    );
    for (const result of settled) {
        if (result.status === "rejected") {
            console.warn("Home menu badge provider failed", result.reason);
            continue;
        }
        for (const [xmlid, value] of Object.entries(result.value || {})) {
            // Coerced, not trusted: a provider is addon code, and a count that
            // is not a number would concatenate into every later sum.
            const count = Number(value);
            if (count > 0) {
                badges[xmlid] = (badges[xmlid] || 0) + count;
            }
        }
    }
    return badges;
}

/** Above this a tile shows "99+": a four-digit count does not fit an icon. */
const BADGE_CEILING = 99;

/**
 * A tile's count, and how to show it. One value rather than three calls, so
 * the ceiling and the wording live here instead of in each launcher.
 *
 * @param {Record<string, number>} badges
 * @param {{ xmlid?: string }} app
 * @returns {{ count: number, text: string, label: string }} count 0 for an app
 *  no provider counted, or that none can name
 */
export function appBadge(badges, app) {
    const count = app.xmlid === undefined ? 0 : badges[app.xmlid] || 0;
    return {
        count,
        text: count > BADGE_CEILING ? `${BADGE_CEILING}+` : String(count),
        // The reader is told the real number, not the shortened one.
        label: _t("%s pending", count),
    };
}
