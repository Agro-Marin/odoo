// @ts-check
import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { makeMockEnv, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { useOwnDebugContext } from "@web/core/debug/debug_context";
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
