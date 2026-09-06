import { beforeEach, expect, mockDate, test } from "@odoo/hoot";
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
