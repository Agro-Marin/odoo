import { provideMailBadges } from "@mail/core/web/home_menu_badges";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");

const apps = [
    { xmlid: "mail.menu_mail_root", module: "mail" },
    { xmlid: "crm.crm_menu_root", module: "crm" },
    { xmlid: "sale.sale_menu_root", module: "sale" },
    { xmlid: "studio.app_1" },
];

function envWith(store) {
    return { services: { "mail.store": store } };
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
        ],
    };
    expect(provideMailBadges(envWith(store), apps)).toEqual({
        "mail.menu_mail_root": 4,
        "crm.crm_menu_root": 3,
    });
});

test("no counts, no badges; a store without groups is fine", () => {
    expect(provideMailBadges(envWith({ inbox: { counter: 0 } }), apps)).toEqual({});
    expect(provideMailBadges(envWith({}), [])).toEqual({});
});
