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
    // "a" and "c" are not in the custom order: they must keep their original
    // relative order (a before c) deterministically — not the unspecified
    // order the old `apps.indexOf` inside the comparator produced.
    const apps = makeApps(["a", "b", "c", "d"]);
    reorderApps(apps, ["d", "b"]);
    // Not-found apps (original order a, c) come first; found apps follow the
    // custom order (d, b).
    expect(xmlids(apps)).toEqual(["a", "c", "d", "b"]);
});

test("reorderApps: a newly installed app does not scramble the customized order", () => {
    // Customized home menu: the user reordered their apps to [e3, e1, e2].
    // "new" is a freshly installed app absent from that saved config.
    const apps = makeApps(["e1", "e2", "e3", "new"]);
    reorderApps(apps, ["e3", "e1", "e2"]);
    // The configured apps keep their EXACT custom order (e3, e1, e2); the new
    // app lands deterministically and cannot shuffle the configured ones.
    expect(xmlids(apps)).toEqual(["new", "e3", "e1", "e2"]);
});
