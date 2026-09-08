// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

const badgeProviders = registry.category("home_menu_badges");
badgeProviders.addValidation({ provide: Function });

/**
 * How long a set of counts serves both launchers. The quick launcher opens on
 * a navbar hover, so without this every mouse crossing the toggle is a full
 * run of every provider -- free while the only provider reads the store, an
 * request storm the moment one asks the server. Long enough to collapse a
 * hover, short enough that deliberately reopening the launcher is fresh.
 */
const BADGE_TTL = 20_000;

/**
 * @type {{
 *  key: string,
 *  at: number,
 *  badges: Promise<Record<string, number>>,
 * } | null}
 */
let cached = null;

/**
 * Which apps a set of counts answers for. Sorted, because the answer is by
 * xmlid and no provider is told to care about order -- the popover ranks its
 * dozen tiles by use and the grid keeps the stored order, and those are the
 * same question asked twice.
 *
 * @param {{ xmlid?: string }[]} apps
 */
function badgeCacheKey(apps) {
    return apps
        .map((app) => app.xmlid ?? "")
        .sort()
        .join("\u0000");
}

/**
 * Drop the counts, so the next launcher to open asks again. For a caller that
 * knows the numbers moved.
 */
export function invalidateHomeMenuBadges() {
    cached = null;
}

badgeProviders.addEventListener("UPDATE", invalidateHomeMenuBadges);

/**
 * Every `home_menu_badges` provider answers with counts by app xmlid; a tile
 * shows their sum. A provider that fails costs its own counts only.
 *
 * The result is shared between the two launchers for `BADGE_TTL`, and a call
 * arriving while one is in flight joins it rather than starting a second.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {{ xmlid?: string }[]} apps
 * @param {{ refresh?: boolean }} [options] `refresh` for a caller the user
 *  asked for by name -- opening the home menu is a request for the counts as
 *  they are now, where crossing the navbar is not. It refills the cache, so
 *  the hover behind it costs nothing.
 * @returns {Promise<Record<string, number>>}
 */
export function loadHomeMenuBadges(env, apps, { refresh = false } = {}) {
    const key = badgeCacheKey(apps);
    const now = Date.now();
    if (!refresh && cached && cached.key === key && now - cached.at < BADGE_TTL) {
        return cached.badges;
    }
    const badges = countHomeMenuBadges(env, apps);
    cached = { key, at: now, badges };
    badges.catch(() => {
        if (cached?.badges === badges) {
            cached = null;
        }
    });
    return badges;
}

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {{ xmlid?: string }[]} apps
 * @returns {Promise<Record<string, number>>}
 */
async function countHomeMenuBadges(env, apps) {
    const providers = badgeProviders.getAll();
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
        label: _t("%s pending", count),
    };
}
