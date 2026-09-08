import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import {
    provideMailBadges,
    subscribeMailBadges,
} from "@mail/core/web/home_menu_badges";
import { animationFrame } from "@odoo/hoot";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");
defineMailModels();

const apps = [
    { xmlid: "mail.menu_mail_root", module: "mail", models: ["discuss.channel"] },
    { xmlid: "crm.crm_menu_root", module: "crm", models: ["crm.lead", "res.partner"] },
    {
        xmlid: "sale.sale_menu_root",
        module: "sale",
        models: ["sale.order", "res.partner"],
    },
    { xmlid: "contacts.menu_contacts", module: "contacts", models: ["res.partner"] },
    { xmlid: "studio.app_1" },
];

/** @param {any} store @returns {import("@web/env").OdooEnv} */
function envWith(store) {
    return /** @type {import("@web/env").OdooEnv} */ ({
        services: { "mail.store": store },
    });
}

test("the inbox counter lands on Discuss, activities due on their module's app", () => {
    const store = {
        inbox: { counter: 4 },
        activityGroups: [
            {
                model: "crm.lead",
                icon: "/crm/static/description/icon.png",
                today_count: 2,
                overdue_count: 1,
                planned_count: 9,
            },
            {
                model: "sale.order",
                icon: "/sale/static/description/icon.png",
                today_count: 0,
                overdue_count: 0,
                planned_count: 3,
            },
            {
                model: "res.partner",
                icon: "/base/static/description/icon.png",
                today_count: 5,
                overdue_count: 0,
            },
            {
                model: "mail.activity",
                icon: "/mail/static/description/icon.png",
                today_count: 7,
                overdue_count: 0,
            },
        ],
    };
    expect(provideMailBadges(envWith(store), apps)).toEqual({
        "mail.menu_mail_root": 4,
        "crm.crm_menu_root": 3,
        "contacts.menu_contacts": 5,
    });
});

test("a model no addon-app owns lands on the first app whose menus open it", () => {
    const store = {
        activityGroups: [
            {
                model: "res.partner",
                icon: "/base/static/description/icon.png",
                today_count: 1,
                overdue_count: 1,
            },
            {
                model: "hr.applicant",
                icon: "/hr_recruitment/static/description/icon.png",
                today_count: 2,
                overdue_count: 0,
            },
        ],
    };
    expect(provideMailBadges(envWith(store), apps.slice(3))).toEqual({
        "contacts.menu_contacts": 2,
    });
});

test("no counts, no badges; a store without groups is fine", () => {
    expect(provideMailBadges(envWith({ inbox: { counter: 0 } }), apps)).toEqual({});
    expect(provideMailBadges(envWith({}), [])).toEqual({});
});

test("shared model ownership stays stable when launcher order changes", () => {
    const store = { activityGroups: [{ model: "shared.model", today_count: 2 }] };
    const owners = [
        { xmlid: "z.app", models: ["shared.model"] },
        { xmlid: "a.app", models: ["shared.model"] },
    ];
    expect(provideMailBadges(envWith(store), owners)).toEqual({ "a.app": 2 });
    expect(provideMailBadges(envWith(store), owners.reverse())).toEqual({ "a.app": 2 });
});

test("mail badge subscriptions follow live inbox and activity changes and detach", async () => {
    const env = await start();
    let updates = 0;
    const stop = subscribeMailBadges(env, () => {
        updates++;
    });
    const store = env.services["mail.store"];
    store.inbox.counter = 42;
    await animationFrame();
    expect(updates).toBeGreaterThan(0);
    const afterInbox = updates;
    store.activityGroups = [{ model: "res.partner", today_count: 7 }];
    await animationFrame();
    expect(updates).toBeGreaterThan(afterInbox);
    stop();
    const beforeDetached = updates;
    store.inbox.counter = 12;
    await animationFrame();
    expect(updates).toBe(beforeDetached);
});
