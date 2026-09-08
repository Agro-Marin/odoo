// @ts-check

import { beforeEach, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { Deferred } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { user } from "@web/core/user";
import {
    HomeMenuLayout,
    orderAfterDrag,
    pinnedApps,
    shownApps,
} from "@web/webclient/home_menu/home_menu_layout";
import { parseHomeMenuConfig } from "@web/webclient/menus/menu_utils";

/** @type {{ changes: unknown, def: InstanceType<typeof Deferred> }[]} */
let writes;

beforeEach(() => {
    writes = [];
    patchWithCleanup(user, {
        settings: { id: 1 },
    });
});

/**
 * @param {unknown} [raw]
 * @param {unknown} [defaultRaw]
 */
function makeLayout(raw, defaultRaw) {
    return new HomeMenuLayout({
        config: parseHomeMenuConfig(raw),
        defaultConfig: parseHomeMenuConfig(defaultRaw ?? null),
        orm: /** @type {any} */ ({
            write: () => true,
            call(
                /** @type {string} */ model,
                /** @type {string} */ method,
                /** @type {any[]} */ args,
            ) {
                const def = new Deferred();
                writes.push({ changes: args[1], def });
                return def;
            },
        }),
    });
}

const sale = { xmlid: "sale" };
const crm = { xmlid: "crm" };
const unnamed = {};

test("pinning and unpinning is the same toggle, and an app with no xmlid has no layout", async () => {
    const layout = makeLayout();
    expect(layout.isPinned(sale)).toBe(false);
    layout.togglePinned(sale);
    expect(layout.config.pinned).toEqual(["sale"]);
    expect(layout.isPinned(sale)).toBe(true);
    layout.togglePinned(sale);
    expect(layout.config.pinned).toEqual([]);

    layout.togglePinned(unnamed);
    layout.toggleHidden(unnamed);
    expect(layout.config.pinned).toEqual([]);
    expect(layout.config.hidden).toEqual([], {
        message: "an app the layout cannot name is left out of it entirely",
    });
});

test("hiding an app unpins it, because a hidden app has nowhere to be pinned to", async () => {
    const layout = makeLayout('{"pinned":["sale","crm"]}');
    layout.toggleHidden(sale);
    expect(layout.config.hidden).toEqual(["sale"]);
    expect(layout.config.pinned).toEqual(["crm"]);
    layout.toggleHidden(sale);
    expect(layout.config.hidden).toEqual([]);
    expect(layout.config.pinned).toEqual(["crm"]);
});

test("a layout is customised only when it differs from the fallback", () => {
    expect(makeLayout().isCustomised).toBe(false);
    expect(makeLayout('{"pinned":["sale"]}').isCustomised).toBe(true);
    expect(makeLayout('{"pinned":["sale"]}', '{"pinned":["sale"]}').isCustomised).toBe(
        false,
    );
});

test("reset restores the fallback layout and hands back its order", async () => {
    const layout = makeLayout(
        '{"order":["crm","sale"],"pinned":["crm"],"hidden":["sale"]}',
        '{"order":["sale","crm"],"pinned":["sale"],"hidden":[]}',
    );
    const { order } = layout.reset();
    expect(order).toEqual(["sale", "crm"]);
    expect(layout.config).toEqual({
        order: ["sale", "crm"],
        pinned: ["sale"],
        hidden: [],
    });
    expect(layout.isCustomised).toBe(false);
});

test("reset stores nothing rather than a copy, so the company's next change is followed", async () => {
    const layout = makeLayout('{"pinned":["sale"]}', '{"pinned":["crm"]}');
    layout.reset();
    await animationFrame();
    expect(writes).toHaveLength(1);
    expect(writes[0].changes).toEqual([{ operation: "reset" }], {
        message: "nothing stored, so the company's next change is picked up",
    });
});

test("quick changes become one write carrying the finished layout, not one per click", async () => {
    const layout = makeLayout();
    layout.togglePinned(sale);
    layout.togglePinned(crm);
    layout.toggleHidden({ xmlid: "stock" });
    await animationFrame();
    expect(writes).toHaveLength(1, {
        message: "one request in flight, never two layouts racing",
    });
    expect(writes[0].changes).toEqual(
        [
            { operation: "pin", xmlid: "sale", value: true },
            { operation: "pin", xmlid: "crm", value: true },
            { operation: "hide", xmlid: "stock", value: true },
        ],
        { message: "and it carries every change, so none is lost" },
    );

    writes[0].def.resolve({ homemenu_config: { version: 2, pinned: ["sale"] } });
    await animationFrame();
    expect(writes).toHaveLength(1, {
        message: "the queued duplicates had nothing left to say",
    });
});

test("a change made while a write is in flight still gets written", async () => {
    const layout = makeLayout();
    layout.togglePinned(sale);
    await animationFrame();
    expect(writes).toHaveLength(1);

    layout.togglePinned(crm);
    writes[0].def.resolve({ homemenu_config: { version: 2, pinned: ["sale"] } });
    await animationFrame();
    expect(writes).toHaveLength(2);
    expect(writes[1].changes).toEqual([
        { operation: "pin", xmlid: "crm", value: true },
    ]);
});

test("shownApps leaves out what the layout hides, and keeps what it cannot name", () => {
    const config = parseHomeMenuConfig('{"hidden":["b"]}');
    const apps = [{ xmlid: "a" }, { xmlid: "b" }, {}, { xmlid: "c" }];
    expect(shownApps(config, apps).map((a) => a.xmlid)).toEqual(["a", undefined, "c"]);
});

test("pinnedApps answers in the pinned order and skips an app that is gone", () => {
    const config = parseHomeMenuConfig('{"pinned":["c","gone","a"]}');
    const apps = [{ xmlid: "a" }, { xmlid: "b" }, { xmlid: "c" }];
    expect(pinnedApps(config, apps).map((a) => a.xmlid)).toEqual(["c", "a"], {
        message: "pinned order, not list order, and no hole for the missing one",
    });
    expect(pinnedApps(parseHomeMenuConfig(null), apps)).toEqual([]);
});

test("orderAfterDrag moves one app and leaves the rest in place", () => {
    const order = ["a", "b", "c", "d"];
    expect(orderAfterDrag(order, "d", "a")).toEqual(["a", "d", "b", "c"]);
    expect(orderAfterDrag(order, "a", "c")).toEqual(["b", "c", "a", "d"]);
    expect(orderAfterDrag(order, "c", undefined)).toEqual(["c", "a", "b", "d"], {
        message: "dropped before everything",
    });
    expect(order).toEqual(["a", "b", "c", "d"], {
        message: "the order handed in is not touched",
    });
});

test("orderAfterDrag refuses an app the order does not hold, rather than moving the last one", () => {
    expect(orderAfterDrag(["a", "b", "c"], "gone", "a")).toBe(null);
    expect(orderAfterDrag(["a", "b", "c"], "c", "gone")).toEqual(["c", "a", "b"]);
});

test("a failed write stays unsaved and retries the same operations", async () => {
    const layout = makeLayout();
    const save = Promise.resolve(layout.togglePinned(sale)).catch(
        (error) => error.message,
    );
    await animationFrame();
    expect(layout.state.status).toBe("saving");
    writes[0].def.reject(new Error("offline"));
    expect(await save).toBe("offline");
    expect(layout.unsaved).toBe(true);
    expect(layout.state.status).toBe("error");
    expect(layout.config.pinned).toEqual(["sale"]);
    const retry = layout.persist();
    await animationFrame();
    expect(writes[1].changes).toEqual(writes[0].changes);
    writes[1].def.resolve({
        homemenu_config: { version: 2, pinned: ["sale", "other-tab"] },
    });
    await retry;
    expect(layout.unsaved).toBe(false);
    expect(layout.state.status).toBe("saved");
    expect(layout.config.pinned).toEqual(["sale", "other-tab"]);
});

test("a post-save callback failure cannot replay committed changes", async () => {
    const layout = makeLayout();
    layout.onSaved = () => {
        throw new Error("render failed");
    };
    const save = Promise.resolve(layout.togglePinned(sale)).catch(
        (error) => error.message,
    );
    await animationFrame();
    writes[0].def.resolve({ homemenu_config: { pinned: ["sale"] } });
    expect(await save).toBe("render failed");
    expect(layout.state.status).toBe("saved");
    expect(layout.unsaved).toBe(false);
    await layout.persist();
    expect(writes).toHaveLength(1);
});
