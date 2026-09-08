// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

const badgeProviders = registry.category("home_menu_badges");
badgeProviders.addValidation({ provide: Function });

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

const BADGE_CEILING = 99;

/**
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
