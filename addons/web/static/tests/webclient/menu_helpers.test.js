// @ts-check

import { expect, test } from "@odoo/hoot";
import { reorderApps } from "@web/webclient/menus/menu_helpers";

/** @param {string[]} xmlids */
function makeApps(xmlids) {
    return xmlids.map((xmlid) => ({ xmlid }));
}

/** @param {{xmlid: string}[]} apps */
function xmlids(apps) {
    return apps.map((a) => a.xmlid);
}

test("reorderApps sorts apps by the given custom order", () => {
    const apps = makeApps(["a", "b", "c"]);
    reorderApps(apps, ["c", "a", "b"]);
    expect(xmlids(apps)).toEqual(["c", "a", "b"]);
});

test("reorderApps keeps the original relative order of apps absent from the order", () => {
    // "a" and "c" aren't in the custom order, so they must keep their original
    // relative order deterministically — not the unspecified order the old
    // `apps.indexOf` inside the comparator produced.
    const apps = makeApps(["a", "b", "c", "d"]);
    reorderApps(apps, ["d", "b"]);
    expect(xmlids(apps)).toEqual(["a", "c", "d", "b"]);
});

test("reorderApps: a newly installed app does not scramble the customized order", () => {
    // "new" is freshly installed and absent from the saved custom order; the
    // configured apps (e3, e1, e2) must keep their exact order regardless.
    const apps = makeApps(["e1", "e2", "e3", "new"]);
    reorderApps(apps, ["e3", "e1", "e2"]);
    expect(xmlids(apps)).toEqual(["new", "e3", "e1", "e2"]);
});
