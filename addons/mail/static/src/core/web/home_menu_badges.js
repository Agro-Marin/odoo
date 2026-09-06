// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

const DISCUSS_APP = "mail.menu_mail_root";

/**
 * Two counts the store already holds at boot, so no request is made: the
 * inbox counter on the Discuss tile, and the activities due today or overdue
 * on the tile of the addon that owns each activity's model. A model whose
 * addon carries no app (a `res.partner` activity, say) has no tile to count on
 * and stays in the systray only.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {{ xmlid?: string, module?: string }[]} apps
 * @returns {Record<string, number>}
 */
export function provideMailBadges(env, apps) {
    const store = env.services["mail.store"];
    /** @type {Record<string, number>} */
    const badges = {};
    const inbox = store.inbox?.counter || 0;
    if (inbox > 0 && apps.some((app) => app.xmlid === DISCUSS_APP)) {
        badges[DISCUSS_APP] = inbox;
    }
    /** @type {Map<string, string>} */
    const appByModule = new Map();
    for (const app of apps) {
        if (app.module && app.xmlid && !appByModule.has(app.module)) {
            appByModule.set(app.module, app.xmlid);
        }
    }
    for (const group of store.activityGroups || []) {
        const due = (group.today_count || 0) + (group.overdue_count || 0);
        const module =
            typeof group.icon === "string" ? group.icon.split("/")[1] : undefined;
        const xmlid = module && appByModule.get(module);
        if (due > 0 && xmlid) {
            badges[xmlid] = (badges[xmlid] || 0) + due;
        }
    }
    return badges;
}

registry.category("home_menu_badges").add("mail", { provide: provideMailBadges });
