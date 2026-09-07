import { beforeEach, expect, mockDate, test } from "@odoo/hoot";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { menuUsage } from "@web/webclient/menus/menu_usage";

const apps = [
    { xmlid: "app.sale", label: "Sale" },
    { xmlid: "app.crm", label: "CRM" },
    { xmlid: "app.stock", label: "Stock" },
    { label: "no xmlid" },
];

beforeEach(() => menuUsage.clear());

test("an app never opened is not ranked", () => {
    expect(menuUsage.rank(apps)).toEqual([]);
    menuUsage.record(apps[3]);
    expect(menuUsage.rank(apps)).toEqual([]);
});

test("more uses rank higher, and the limit trims the tail", () => {
    menuUsage.record(apps[2]);
    menuUsage.record(apps[0]);
    menuUsage.record(apps[0]);
    expect(menuUsage.rank(apps).map((a) => a.xmlid)).toEqual(["app.sale", "app.stock"]);
    expect(menuUsage.rank(apps, 1).map((a) => a.xmlid)).toEqual(["app.sale"]);
});

test("a count halves every week, so a fresh use beats an old burst", () => {
    mockDate("2026-01-01T00:00:00");
    menuUsage.record(apps[0]);
    menuUsage.record(apps[0]);
    menuUsage.record(apps[0]);
    mockDate("2026-01-22T00:00:00");
    menuUsage.record(apps[1]);
    expect(menuUsage.rank(apps).map((a) => a.xmlid)).toEqual(["app.crm", "app.sale"]);
});

test("the table is bounded, dropping the least valuable entries", () => {
    for (let i = 0; i < 60; i++) {
        menuUsage.record({ xmlid: `app.${i}` });
    }
    const all = Array.from({ length: 60 }, (_, i) => ({ xmlid: `app.${i}` }));
    const kept = menuUsage.rank(all).map((a) => a.xmlid);
    expect(kept).toHaveLength(50);
    expect(kept).not.toInclude("app.0");
    expect(kept).toInclude("app.59");
});

test("a corrupt or foreign table reads as empty, a malformed entry as unused", () => {
    const key = `webclient_menu_usage:${user.userId}`;
    for (const raw of ["[1,2]", "{", "null", '{"app.sale":"x"}']) {
        browser.localStorage.setItem(key, raw);
        expect(menuUsage.rank(apps)).toEqual([], { message: `table ${raw}` });
    }
    browser.localStorage.setItem(
        key,
        '{"app.sale":{"n":"oops","t":null},"app.crm":{"n":2,"t":0}}',
    );
    expect(menuUsage.rank(apps).map((a) => a.xmlid)).toEqual(["app.crm"], {
        message: "an entry without a positive count was never a use",
    });
});

test("rank keeps the caller's order when frecency ties, so the input order is part of the answer", () => {
    // Not a curiosity: it is why the home menu ranks its recents over the grid
    // order rather than over the cheaper unsorted list. Array.sort is stable,
    // so entries on the same count and the same millisecond come back in the
    // order they went in.
    browser.localStorage.setItem(
        `webclient_menu_usage:${user.userId}`,
        JSON.stringify({
            "app.sale": { n: 3, t: 1000 },
            "app.crm": { n: 3, t: 1000 },
            "app.stock": { n: 3, t: 1000 },
        }),
    );
    const tied = apps.slice(0, 3);
    expect(menuUsage.rank(tied).map((a) => a.xmlid)).toEqual([
        "app.sale",
        "app.crm",
        "app.stock",
    ]);
    expect(menuUsage.rank([tied[2], tied[0], tied[1]]).map((a) => a.xmlid)).toEqual([
        "app.stock",
        "app.sale",
        "app.crm",
    ]);
});
