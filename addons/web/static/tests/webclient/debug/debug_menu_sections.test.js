// @ts-check
import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { makeMockEnv, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { useOwnDebugContext } from "@web/core/debug/debug_context";
import { registry } from "@web/core/registry";
import { DebugMenu } from "@web/webclient/debug/debug_menu";

class Parent extends Component {
    static template = xml`<DebugMenu/>`;
    static components = { DebugMenu };
    static props = ["*"];
    setup() {
        useOwnDebugContext({ categories: ["default"] });
    }
}

describe.current.tags("desktop");

test("the debug menu renders no empty section header", async () => {
    onRpc("has_access", () => true);
    await makeMockEnv({ debug: "1" });
    await mountWithCleanup(Parent);
    await click(".o_debug_manager button");
    await animationFrame();
    await animationFrame();
    const labels = queryAll(".dropdown-header").map((/** @type {any} */ h) =>
        h.textContent.trim(),
    );
    expect(labels.length).toBeGreaterThan(0);
    expect(labels.filter((/** @type {any} */ l) => !l)).toEqual([]);
});

test("a section registered without a sequence sorts at the default, not adrift", async () => {
    // `sequence` is optional in the debug_section schema. An entry registered
    // without one used to sort as `undefined`, which compares equal to every
    // number: an inconsistent comparator, so which sections move depends on the
    // order they arrive in, and sections that do declare a sequence can move
    // too. This pins the offender's own place, which is deterministic.
    onRpc("has_access", () => true);
    registry
        .category("debug_section")
        .add("zz_before", { label: "ZZ Before", sequence: 45 })
        .add("zz_default", { label: "ZZ Default" })
        .add("zz_after", { label: "ZZ After", sequence: 55 });
    registry
        .category("debug")
        .category("default")
        .add("zz_c", () => ({
            type: "item",
            description: "c",
            section: "zz_after",
            sequence: 1,
            callback() {},
        }))
        .add("zz_a", () => ({
            type: "item",
            description: "a",
            section: "zz_before",
            sequence: 1,
            callback() {},
        }))
        .add("zz_b", () => ({
            type: "item",
            description: "b",
            section: "zz_default",
            sequence: 1,
            callback() {},
        }));

    await makeMockEnv({ debug: "1" });
    await mountWithCleanup(Parent);
    await click(".o_debug_manager button");
    await animationFrame();
    await animationFrame();

    const ours = queryAll(".dropdown-header")
        .map((/** @type {any} */ h) => h.textContent.trim())
        .filter((/** @type {string} */ label) => label.startsWith("ZZ "));
    expect(ours).toEqual(["ZZ Before", "ZZ Default", "ZZ After"]);
});
