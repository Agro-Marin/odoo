// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import {
    getDisplayedRegistryItems,
    MENU_REGISTRY_VALIDATION,
} from "@web/search/utils/misc";

describe.current.tags("headless");

class ProbeCog extends Component {
    static template = xml`<div class="o_probe_cog"/>`;
    static props = {};
}

/**
 * @param {Record<string, any>} [overrides]
 */
function makeCogMenu(overrides = {}) {
    const menu = Object.create(CogMenu.prototype);
    menu.env = /** @type {any} */ ({});
    menu.props = { items: {} };
    menu.registryItems = [];
    menu.actionItems = [];
    Object.assign(menu, overrides);
    return menu;
}

describe("cogItems", () => {
    test("registry items and action items are merged", () => {
        const menu = makeCogMenu({
            registryItems: [{ key: "a", groupNumber: 1 }],
            actionItems: [{ key: "b", groupNumber: 1 }],
        });
        expect(menu.cogItems.map((/** @type {any} */ i) => i.key)).toEqual(["a", "b"]);
    });

    test("they interleave by groupNumber rather than by source", () => {
        const menu = makeCogMenu({
            registryItems: [{ key: "late", groupNumber: 100 }],
            actionItems: [{ key: "early", groupNumber: 1 }],
        });
        expect(menu.cogItems.map((/** @type {any} */ i) => i.key)).toEqual([
            "early",
            "late",
        ]);
    });

    test("a missing groupNumber sorts as zero, ahead of everything", () => {
        const menu = makeCogMenu({
            registryItems: [{ key: "none" }],
            actionItems: [{ key: "one", groupNumber: 1 }],
        });
        expect(menu.cogItems.map((/** @type {any} */ i) => i.key)).toEqual([
            "none",
            "one",
        ]);
    });

    test("the sort is stable within a group", () => {
        const menu = makeCogMenu({
            registryItems: [
                { key: "a", groupNumber: 2 },
                { key: "b", groupNumber: 2 },
            ],
            actionItems: [{ key: "c", groupNumber: 2 }],
        });
        expect(menu.cogItems.map((/** @type {any} */ i) => i.key)).toEqual([
            "a",
            "b",
            "c",
        ]);
    });

    test("it does not mutate either source list", () => {
        const registryItems = [
            { key: "b", groupNumber: 2 },
            { key: "a", groupNumber: 1 },
        ];
        const menu = makeCogMenu({ registryItems });
        menu.cogItems;
        expect(registryItems.map((i) => i.key)).toEqual(["b", "a"]);
    });

    test("action items that have not loaded yet are treated as none", () => {
        const menu = makeCogMenu({
            registryItems: [{ key: "a" }],
            actionItems: undefined,
        });
        expect(menu.cogItems.map((/** @type {any} */ i) => i.key)).toEqual(["a"]);
    });
});

describe("hasItems", () => {
    test("nothing to show, and no print key, answers undefined", () => {
        expect(makeCogMenu().hasItems).toBe(undefined);
    });

    test("nothing to show with an empty print list answers zero", () => {
        expect(makeCogMenu({ props: { items: { print: [] } } }).hasItems).toBe(0);
    });

    test("a cog item alone is enough", () => {
        expect(makeCogMenu({ registryItems: [{ key: "a" }] }).hasItems).toBe(1);
    });

    test("a print item alone is enough", () => {
        const menu = makeCogMenu({
            props: { items: { print: [{ id: 1 }, { id: 2 }] } },
        });
        expect(menu.hasItems).toBe(2);
    });

    test("an absent print key does not throw", () => {
        expect(() => makeCogMenu({ props: { items: {} } }).hasItems).not.toThrow();
    });
});

describe("getDisplayedRegistryItems", () => {
    const probeRegistry = registry.category("test.cog_menu_probe");

    /**
     * @param {string} key
     * @param {Record<string, any>} [entry]
     */
    function registerProbe(key, entry = {}) {
        probeRegistry.add(key, { Component: ProbeCog, groupNumber: 5, ...entry });
        after(() => probeRegistry.remove(key));
    }

    test("declares the shared menu validation", () => {
        expect(MENU_REGISTRY_VALIDATION.isDisplayed).toEqual({
            type: Function,
            optional: true,
        });
    });

    test("an async isDisplayed resolving false hides the item", async () => {
        registerProbe("probe-hidden", { isDisplayed: async () => false });
        const items = await getDisplayedRegistryItems(
            probeRegistry,
            /** @type {any} */ ({}),
        );
        expect(items.map((i) => i.key)).not.toInclude("probe-hidden");
    });

    test("an async isDisplayed resolving true shows it", async () => {
        registerProbe("probe-shown", { isDisplayed: async () => true });
        const items = await getDisplayedRegistryItems(
            probeRegistry,
            /** @type {any} */ ({}),
        );
        expect(items.map((i) => i.key)).toInclude("probe-shown");
    });

    test("an entry with no isDisplayed is shown", async () => {
        registerProbe("probe-plain");
        const items = await getDisplayedRegistryItems(
            probeRegistry,
            /** @type {any} */ ({}),
        );
        expect(items.map((i) => i.key)).toInclude("probe-plain");
    });

    test("isDisplayed receives the env", async () => {
        /** @type {string[]} */
        const seen = [];
        const env = /** @type {any} */ ({ marker: 1 });
        registerProbe("probe-env", {
            isDisplayed: (/** @type {any} */ e) => {
                seen.push(e);
                return true;
            },
        });
        await getDisplayedRegistryItems(probeRegistry, env);
        expect(seen).toInclude(env);
    });

    test("the key is the registry key, not the component's class name", async () => {
        registerProbe("probe-keyed");
        const items = await getDisplayedRegistryItems(
            probeRegistry,
            /** @type {any} */ ({}),
        );
        const item = /** @type {any} */ (items.find((i) => i.key === "probe-keyed"));
        expect(item).not.toBe(undefined);
        expect(item.Component).toBe(ProbeCog);
        expect(item.key).not.toBe(ProbeCog.name);
    });
});
