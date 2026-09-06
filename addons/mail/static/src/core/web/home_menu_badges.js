// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

const DISCUSS_APP = "mail.menu_mail_root";

/**
 * Two counts the store already holds at boot, so no request is made: the
 * inbox counter on the Discuss tile, and the activities due today or overdue
 * on one app's tile per model: the app of the addon that owns the model when
 * it has one, else the app that opens on the model (`res.partner` lands on
 * Contacts this way), else the first app with a menu on it. A model no app
 * opens stays in the systray only.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {{ xmlid?: string, module?: string, models?: string[] }[]} apps
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
    /** @type {Map<string, string>} */
    const appByRootModel = new Map();
    /** @type {Map<string, string>} */
    const appByModel = new Map();
    for (const app of apps) {
        if (!app.xmlid) {
            continue;
        }
        if (app.module && !appByModule.has(app.module)) {
            appByModule.set(app.module, app.xmlid);
        }
        // An app's first model is the one its root menu opens.
        (app.models || []).forEach((model, index) => {
            if (index === 0 && !appByRootModel.has(model)) {
                appByRootModel.set(model, app.xmlid);
            }
            if (!appByModel.has(model)) {
                appByModel.set(model, app.xmlid);
            }
        });
    }
    for (const group of store.activityGroups || []) {
        const due = (group.today_count || 0) + (group.overdue_count || 0);
        const module =
            typeof group.icon === "string" ? group.icon.split("/")[1] : undefined;
        const xmlid =
            (module && appByModule.get(module)) ||
            appByRootModel.get(group.model) ||
            appByModel.get(group.model);
        if (due > 0 && xmlid) {
            badges[xmlid] = (badges[xmlid] || 0) + due;
        }
    }
    return badges;
}

registry.category("home_menu_badges").add("mail", { provide: provideMailBadges });
