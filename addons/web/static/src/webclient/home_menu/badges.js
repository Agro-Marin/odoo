// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

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
