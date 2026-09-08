// @ts-check
/** @odoo-module native */

import { Record as MailRecord } from "@mail/core/common/record";
import { registry } from "@web/core/registry";

const DISCUSS_APP = "mail.menu_mail_root";

/**
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
    for (const app of [...apps].sort((a, b) =>
        (a.xmlid || "").localeCompare(b.xmlid || ""),
    )) {
        if (!app.xmlid) {
            continue;
        }
        if (app.module && !appByModule.has(app.module)) {
            appByModule.set(app.module, app.xmlid);
        }
        const xmlid = app.xmlid;
        // An app's first model is the one its root menu opens.
        (app.models || []).forEach((model, index) => {
            if (index === 0 && !appByRootModel.has(model)) {
                appByRootModel.set(model, xmlid);
            }
            if (!appByModel.has(model)) {
                appByModel.set(model, xmlid);
            }
        });
    }
    /** @type {{ model?: string, icon?: string, today_count?: number, overdue_count?: number }[]} */
    const groups = store.activityGroups || [];
    for (const group of groups) {
        if (group.model === "mail.activity") {
            continue;
        }
        const due = (group.today_count || 0) + (group.overdue_count || 0);
        const module =
            typeof group.icon === "string" ? group.icon.split("/")[1] : undefined;
        const xmlid =
            (module && appByModule.get(module)) ||
            appByRootModel.get(group.model ?? "") ||
            appByModel.get(group.model ?? "");
        if (due > 0 && xmlid) {
            badges[xmlid] = (badges[xmlid] || 0) + due;
        }
    }
    return badges;
}

/** @param {import("@web/env").OdooEnv} env @param {() => void} changed */
export function subscribeMailBadges(env, changed) {
    const store = env.services["mail.store"];
    let stopInbox = () => {};
    const watchInbox = () => {
        stopInbox();
        stopInbox = store.inbox
            ? MailRecord.onChange(store.inbox, "counter", changed)
            : () => {};
    };
    watchInbox();
    const stopStore = MailRecord.onChange(store, ["activityGroups", "inbox"], () => {
        watchInbox();
        changed();
    });
    return () => {
        stopStore();
        stopInbox();
    };
}

registry.category("home_menu_badges").add("mail", {
    provide: provideMailBadges,
    subscribe: subscribeMailBadges,
});
