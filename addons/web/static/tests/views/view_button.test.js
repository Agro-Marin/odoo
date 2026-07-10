// @ts-check

// Side-effect imports: register the remaining shared_components entries and
// install the registry's validation schema (M2).
import "@web/views/form/form_utils";
import "@web/views/view_utils";

import { expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { Component, useRef, useState, xml } from "@odoo/owl";
import {
    contains,
    mockService,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { MultiRecordViewButton } from "@web/views/view_button/multi_record_view_button";
import { ViewButton } from "@web/views/view_button/view_button";
import { useViewButtons } from "@web/views/view_button/view_button_hook";

/**
 * Mount a ViewButton (or subclass) declared by `buttonXml`, wired to useViewButtons.
 * @param {string} buttonXml
 */
async function mountButton(buttonXml) {
    class Parent extends Component {
        static components = { ViewButton, MultiRecordViewButton };
        static props = ["*"];
        static template = xml`<div t-ref="root">${buttonXml}</div>`;
        setup() {
            useViewButtons(useRef("root"));
        }
    }
    await mountWithCleanup(Parent);
}

// ── getClassName: Bootstrap rank resolution (view_button.js:getClassName) ──

test("getClassName: oe_highlight legacy class maps to btn-primary", async () => {
    await mountButton(
        `<ViewButton className="'oe_highlight'" string="'X'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button").toHaveClass(["btn", "btn-primary"]);
    expect("button").not.toHaveClass("btn-secondary");
});

test("getClassName: empty class + defaultRank applies that rank", async () => {
    await mountButton(
        `<ViewButton className="''" defaultRank="'btn-primary'" string="'X'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button").toHaveClass(["btn", "btn-primary"]);
});

test("getClassName: empty class + no rank falls back to btn-secondary", async () => {
    await mountButton(
        `<ViewButton className="''" string="'X'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button").toHaveClass(["btn", "btn-secondary"]);
});

test("getClassName: a custom non-rank class does NOT get btn-secondary", async () => {
    await mountButton(
        `<ViewButton className="'my-class'" string="'X'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button").toHaveClass(["btn", "my-class"]);
    expect("button").not.toHaveClass("btn-secondary");
});

test("getClassName: size adds btn-<size>", async () => {
    await mountButton(
        `<ViewButton className="''" size="'sm'" string="'X'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button").toHaveClass("btn-sm");
});

// ── iconFromString: FA7 / FA4 / odoo-icon / image parsing (view_button.js) ──

test("iconFromString: FA4 bare name normalizes to fa-solid", async () => {
    await mountButton(
        `<ViewButton icon="'fa-edit'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button i.o_button_icon").toHaveClass(["fa-solid", "fa-edit"]);
});

test("iconFromString: FA4 outline -o maps to fa-regular and strips -o", async () => {
    await mountButton(
        `<ViewButton icon="'fa-star-o'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button i.o_button_icon").toHaveClass(["fa-regular", "fa-star"]);
    expect("button i.o_button_icon").not.toHaveClass("fa-star-o");
});

test("iconFromString: odoo icon oi- prefix", async () => {
    await mountButton(
        `<ViewButton icon="'oi-settings'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button i.o_button_icon").toHaveClass(["oi", "oi-fw", "oi-settings"]);
});

test("iconFromString: a non-icon string renders an <img>", async () => {
    await mountButton(
        `<ViewButton icon="'/web/static/img/x.png'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button img").toHaveAttribute("src", "/web/static/img/x.png");
});

// ── tooltip (P1): lazy getter, gated by hasBigTooltip ──

test("tooltip (P1): without help/debug there is no tooltip template attribute", async () => {
    await mountButton(`<ViewButton string="'X'" clickParams="{ type: 'object' }"/>`);
    expect("button").not.toHaveAttribute("data-tooltip-template");
});

test("tooltip (P1): help text activates the lazy tooltip getter", async () => {
    await mountButton(
        `<ViewButton string="'X'" clickParams="{ type: 'object', help: 'Helpful' }"/>`,
    );
    expect("button").toHaveAttribute(
        "data-tooltip-template",
        "views.ViewButtonTooltip",
    );
});

// ── L1: MultiRecordViewButton must not mutate the shared arch clickParams ──

test("MultiRecordViewButton (L1): does not mutate the shared clickParams object", async () => {
    mockService("action", { doActionButton() {} });
    const clickParams = { type: "object", name: "act" };
    class Parent extends Component {
        static components = { MultiRecordViewButton };
        static props = ["*"];
        static template = xml`
            <div t-ref="root">
                <MultiRecordViewButton list="list" domain="[]" clickParams="clickParams" string="'Go'"/>
            </div>`;
        setup() {
            useViewButtons(useRef("root"));
            this.clickParams = clickParams;
            this.list = {
                getResIds: async () => [1, 2],
                resModel: "res.partner",
                context: {},
                evalContext: {},
            };
        }
    }
    await mountWithCleanup(Parent);
    await contains("button").click();
    await animationFrame();
    // The buggy implementation grafted `buttonContext` onto the shared arch object.
    expect("buttonContext" in clickParams).toBe(false);
});

test("prop shape (M1): accepts the union types real call sites pass", async () => {
    // OWL prop validation throws on mount in test mode, so a clean render proves
    // the typed shape accepts icon=false, an object context, a numeric id, and a
    // string tabindex — the shapes seen in list/kanban/x2many/payrun call sites.
    await mountButton(
        `<ViewButton id="42" icon="false" context="{ foo: 1 }" tabindex="'-1'" record="{ resId: 1 }" string="'X'" clickParams="{ type: 'object' }"/>`,
    );
    expect("button").toHaveCount(1);
    expect("button i").toHaveCount(0); // icon=false -> no icon element rendered
});

test("shared_components (M2): validation schema installed; every entry is callable", () => {
    const shared = registry.category("shared_components");
    // The schema is the function predicate installed by view_utils.
    expect(typeof shared.validationSchema).toBe("function");
    // Contract: callables accepted, non-callables rejected.
    expect(shared.validationSchema(function () {})).toBe(true);
    expect(shared.validationSchema({})).toBe(false);
    // Every real entry (a Component class + hooks/utilities) satisfies it.
    for (const key of [
        "ViewButton",
        "executeButtonCallback",
        "useViewButtons",
        "computeViewClassName",
        "loadSubViews",
        "useFormViewInDialog",
    ]) {
        expect(shared.validationSchema(shared.get(key))).toBe(true);
    }
});

test("R2 probe: an OWL re-render of the button mid-action keeps it disabled", async () => {
    // Settles the R2 hypothesis ("imperative disabling fights reactive renders"):
    // executeButtonCallback disables buttons via setAttribute (outside OWL's vdom).
    // If a routine OWL re-render that patches the button wiped that attribute, the
    // double-click guard would silently reopen while the action is still running.
    const def = new Deferred();
    mockService("action", {
        doActionButton() {
            return def; // stay pending so the button stays disabled
        },
    });

    let parent;
    class Parent extends Component {
        static components = { ViewButton };
        static props = ["*"];
        static template = xml`
            <div t-ref="root">
                <ViewButton string="state.label" clickParams="{ type: 'object', name: 'act' }" record="{ resId: 1 }"/>
            </div>`;
        setup() {
            parent = this;
            this.state = useState({ label: "Go" });
            useViewButtons(useRef("root"));
        }
    }
    await mountWithCleanup(Parent);

    // 1. Click: the action is pending and executeButtonCallback disables the button.
    await contains("button").click();
    expect("button").toHaveAttribute("disabled");

    // 2. Change the button's `string` prop -> OWL re-renders and patches the button
    //    element (not skipped by child-component memoization) while still pending.
    parent.state.label = "Running";
    await animationFrame();
    expect("button").toHaveText("Running"); // the element was genuinely patched

    // 3. The imperatively-set disabled must survive that patch.
    expect("button").toHaveAttribute("disabled");

    // 4. Completing the action re-enables the button.
    def.resolve();
    await animationFrame();
    expect("button").not.toHaveAttribute("disabled");
});
