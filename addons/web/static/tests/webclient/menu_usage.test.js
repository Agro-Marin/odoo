import { beforeEach, expect, mockDate, runAllTimers, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { session } from "@web/session";
import { menuUsage, mergeUsage } from "@web/webclient/menus/menu_usage";

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
    const key = `webclient_menu_usage:${session.db}:${user.userId}`;
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

test("the table follows the user, and the browser's copy is merged back in", () => {
    patchWithCleanup(user, {
        settings: {
            homemenu_usage: {
                "app.sale": { n: 9, t: 5000 },
                "app.crm": { n: 1, t: 1000 },
            },
        },
    });
    browser.localStorage.setItem(
        `webclient_menu_usage:${session.db}:${user.userId}`,
        JSON.stringify({
            "app.crm": { n: 4, t: 9000 },
            "app.stock": { n: 2, t: 2000 },
        }),
    );
    expect(menuUsage.rank(apps).map((a) => a.xmlid)).toEqual([
        "app.sale",
        "app.crm",
        "app.stock",
    ]);
});

test("merging takes the higher count and the later use, and never sums", () => {
    expect(
        mergeUsage(
            { a: { n: 3, t: 10 }, b: { n: 1, t: 50 } },
            { a: { n: 5, t: 4 }, c: { n: 2, t: 7 } },
        ),
    ).toEqual({
        a: { n: 5, t: 10 },
        b: { n: 1, t: 50 },
        c: { n: 2, t: 7 },
    });
});

test("a burst of navigation is one write, not one per menu", async () => {
    /** @type {unknown[][]} */
    const writes = [];
    patchWithCleanup(user, {
        settings: {},
        setUserSettings: async (key, value) => {
            writes.push([key, value && Object.keys(value).length]);
        },
    });
    for (const app of [apps[0], apps[1], apps[2], apps[0]]) {
        menuUsage.record(app);
    }
    expect(writes).toEqual([], { message: "nothing goes out on the click itself" });
    await runAllTimers();
    expect(writes).toEqual([["homemenu_usage", 3]], {
        message: "one write carrying the finished table",
    });
});

test("rank keeps the caller's order when frecency ties, so the input order is part of the answer", () => {
    browser.localStorage.setItem(
        `webclient_menu_usage:${session.db}:${user.userId}`,
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

test("browser usage is isolated by database even for the same user ID", () => {
    patchWithCleanup(session, { db: "launcher_database_a" });
    menuUsage.record(apps[0]);
    patchWithCleanup(session, { db: "launcher_database_b" });
    expect(menuUsage.rank(apps)).toEqual([]);
    menuUsage.record(apps[1]);
    patchWithCleanup(session, { db: "launcher_database_a" });
    expect(menuUsage.rank(apps).map((app) => app.xmlid)).toEqual(["app.sale"]);
});
