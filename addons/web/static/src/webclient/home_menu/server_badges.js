// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

/**
 * @param {import("@web/env").OdooEnv} env
 * @returns {Promise<Record<string, number>>}
 */
export async function provideServerBadges(env) {
    return env.services.orm.call("home.menu.badge", "get_badges", []);
}

registry.category("home_menu_badges").add("server", { provide: provideServerBadges });
