// @ts-check

import { expect, getFixture, test } from "@odoo/hoot";
import { click, keyDown, keyUp, press, queryAll, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { reactive } from "@odoo/owl";
import {
    contains,
    defineModels,
    fields,
    getService,
    models,
    mountWithCleanup,
    mountWithSearch,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { WebClient } from "@web/webclient/webclient";

class Foo extends models.Model {
    _views = {
        kanban: `<kanban><t t-name="card"></t></kanban>`,
    };
}
defineModels([Foo]);

test("default embedded infos arrays are per-instance, not shared globally", async () => {
    // Default embedded infos must be a fresh instance per panel — a shared
    // module constant would let a single push leak into every panel.
    const cp1 = await mountWithSearch(ControlPanel, { resModel: "foo" });
    const cp2 = await mountWithSearch(ControlPanel, { resModel: "foo" });

    expect(cp1.state.embeddedInfos.embeddedActions).not.toBe(
        cp2.state.embeddedInfos.embeddedActions,
    );
    cp1.state.embeddedInfos.embeddedActions.push("leak");
    expect(cp2.state.embeddedInfos.embeddedActions).toHaveLength(0);
});

test("simple rendering", async () => {
    await mountWithSearch(ControlPanel, { resModel: "foo" });

    expect(`.o_control_panel_breadcrumbs`).toHaveCount(1);
    expect(`.o_control_panel_actions`).toHaveCount(1);
    expect(`.o_control_panel_actions > *`).toHaveCount(0);
    expect(`.o_control_panel_navigation`).toHaveCount(1);
    expect(`.o_control_panel_navigation > *`).toHaveCount(0);
    expect(`.o_cp_switch_buttons`).toHaveCount(0);
    expect(`.o_breadcrumb`).toHaveCount(1);
});

test.tags("desktop");
test("breadcrumbs", async () => {
    await mountWithSearch(
        ControlPanel,
        { resModel: "foo" },
        {
            breadcrumbs: [
                {
                    jsId: "controller_7",
                    name: "Previous",
                    onSelected: () => expect.step("controller_7"),
                },
                {
                    jsId: "controller_9",
                    name: "Current",
                    onSelected: () => expect.step("controller_9"),
                },
            ],
        },
    );

    const breadcrumbItems = queryAll(
        `.o_breadcrumb li.breadcrumb-item, .o_breadcrumb .active`,
    );
    expect(breadcrumbItems).toHaveCount(2);
    expect(breadcrumbItems[0]).toHaveText("Previous");
    expect(breadcrumbItems[1]).toHaveText("Current");
    expect(breadcrumbItems[1]).toHaveClass("active");

    await click(breadcrumbItems[0]);
    expect.verifySteps(["controller_7"]);
});

test.tags("desktop");
test("view switcher", async () => {
    await mountWithSearch(
        ControlPanel,
        { resModel: "foo" },
        {
            viewSwitcherEntries: [
                { type: "list", active: true, icon: "oi-view-list", name: "List" },
                { type: "kanban", icon: "oi-view-kanban", name: "Kanban" },
            ],
        },
    );
    expect(`.o_control_panel_navigation .o_cp_switch_buttons`).toHaveCount(1);
    expect(`.o_switch_view`).toHaveCount(2);

    const views = queryAll`.o_switch_view`;
    expect(views[0]).toHaveAttribute("data-tooltip", "List");
    expect(views[0]).toHaveClass("active");
    expect(`.o_switch_view:eq(0) .oi-view-list`).toHaveCount(1);
    expect(views[1]).toHaveAttribute("data-tooltip", "Kanban");
    expect(views[1]).not.toHaveClass("active");
    expect(`.o_switch_view:eq(1) .oi-view-kanban`).toHaveCount(1);

    getService("action").switchView = (viewType) => expect.step(viewType);
    await click(views[1]);
    expect.verifySteps(["kanban"]);
});

test.tags("desktop");
test("view switcher (middle click)", async () => {
    await mountWithSearch(
        ControlPanel,
        { resModel: "foo" },
        {
            viewSwitcherEntries: [
                { type: "list", active: true, icon: "oi-view-list", name: "List" },
                { type: "kanban", icon: "oi-view-kanban", name: "Kanban" },
            ],
        },
    );
    expect(`.o_control_panel_navigation .o_cp_switch_buttons`).toHaveCount(1);
    expect(`.o_switch_view`).toHaveCount(2);

    getService("action").switchView = (viewType, props, options) =>
        expect.step(
            `${viewType} -- ${JSON.stringify(props)} -- ${JSON.stringify(options)}`,
        );

    await contains(".o_switch_view.o_kanban").click({ ctrlKey: true });
    expect.verifySteps([`kanban -- {} -- {"newWindow":true}`]);
});

test.tags("desktop");
test("views aria labels", async () => {
    await mountWithSearch(
        ControlPanel,
        { resModel: "foo" },
        {
            viewSwitcherEntries: [
                { type: "list", active: true, icon: "oi-view-list", name: "List" },
                { type: "kanban", icon: "oi-view-kanban", name: "Kanban" },
            ],
        },
    );

    const views = queryAll`.o_switch_view`;
    expect(views[0]).toHaveAttribute("aria-label", "List View");
    expect(views[1]).toHaveAttribute("aria-label", "Kanban View");
});

test.tags("mobile");
test("view switcher on mobile", async () => {
    await mountWithSearch(
        ControlPanel,
        { resModel: "foo" },
        {
            viewSwitcherEntries: [
                { type: "list", active: true, icon: "oi-view-list", name: "List" },
                { type: "kanban", icon: "oi-view-kanban", name: "Kanban" },
            ],
        },
    );
    expect(`.o_control_panel_navigation .o_cp_switch_buttons`).toHaveCount(1);

    await click(".o_control_panel_navigation .o_cp_switch_buttons .dropdown-toggle");
    await animationFrame();

    expect(`.dropdown-item`).toHaveCount(2);

    const views = queryAll`.dropdown-item`;
    expect(views[0]).toHaveText("List");
    expect(views[0]).toHaveClass("selected");
    expect(queryAll(`.oi-view-list`, { root: views[0] })).toHaveCount(1);
    expect(views[1]).toHaveText("Kanban");
    expect(views[1]).not.toHaveClass("selected");
    expect(queryAll(`.oi-view-kanban`, { root: views[1] })).toHaveCount(1);

    getService("action").switchView = (viewType) => expect.step(viewType);
    await click(views[1]);
    expect.verifySteps(["kanban"]);
});

test("pager", async () => {
    const pagerProps = reactive({
        offset: 0,
        limit: 10,
        total: 50,
        onUpdate: () => {},
    });

    await mountWithSearch(ControlPanel, { resModel: "foo" }, { pagerProps });
    expect(`.o_pager`).toHaveCount(1);

    pagerProps.total = 0;
    await animationFrame();
    expect(`.o_pager`).toHaveCount(0);
});

test("view switcher hotkey cycles through views", async () => {
    onRpc("has_group", () => true);

    await mountWithCleanup(WebClient);
    await getService("action").doAction({
        res_model: "foo",
        type: "ir.actions.act_window",
        views: [
            [false, "list"],
            [false, "kanban"],
        ],
    });
    expect(`.o_list_view`).toHaveCount(1);

    await press(["alt", "shift", "v"]);
    await animationFrame();
    expect(`.o_kanban_view`).toHaveCount(1);

    await press(["alt", "shift", "v"]);
    await animationFrame();
    expect(`.o_list_view`).toHaveCount(1);
});

test.tags("desktop");
test("hotkey overlay not overlapped by active view button", async () => {
    onRpc("has_group", () => true);

    await mountWithCleanup(WebClient);
    await getService("action").doAction({
        res_model: "foo",
        type: "ir.actions.act_window",
        views: [
            [false, "list"],
            [false, "kanban"],
        ],
    });

    await keyDown("alt");
    expect(`.o_cp_switch_buttons .o_web_hotkey_overlay`).toHaveCount(1);
    expect(`.o_switch_view.active`).toHaveCount(1);

    const hotkeyZIndex = Number(
        getComputedStyle(queryFirst(`.o_cp_switch_buttons .o_web_hotkey_overlay`))
            .zIndex,
    );
    const buttonZIndex = Number(
        getComputedStyle(queryFirst(`.o_switch_view.active`)).zIndex,
    );

    expect(hotkeyZIndex).toBeGreaterThan(buttonZIndex);

    await keyUp("alt");
    expect(`.o_cp_switch_buttons .o_web_hotkey_overlay`).toHaveCount(0);
});

test.tags("desktop");
test("control panel layout buttons in dialog", async () => {
    onRpc("has_group", () => true);
    Foo._fields.char = fields.Char();
    Foo._records = [
        {
            char: "a",
        },
        {
            char: "b",
        },
    ];
    Foo._views["list"] = `<list editable="top"><field name="char"/></list>`;

    await mountWithCleanup(WebClient);
    await getService("action").doAction({
        res_model: "foo",
        type: "ir.actions.act_window",
        target: "new",
        views: [[false, "list"]],
    });
    expect(`.o_list_view`).toHaveCount(1);
    await contains(".o_data_cell").click();
    expect(".modal-footer button:visible").toHaveCount(2);
    expect(".o_control_panel_main_buttons button").toHaveCount(0, {
        message:
            "layout buttons are not replicated in the control panel when inside a dialog",
    });
});

test.tags("mobile");
test("Control panel is shown/hide on top when scrolling", async () => {
    await mountWithSearch(
        ControlPanel,
        { resModel: "foo" },
        {
            viewSwitcherEntries: [
                { type: "list", active: true, icon: "oi-view-list", name: "List" },
                { type: "kanban", icon: "oi-view-kanban", name: "Kanban" },
            ],
        },
    );
    const contentHeight = 200;
    const sampleContent = document.createElement("div");
    sampleContent.style.minHeight = `${2 * contentHeight}px`;
    const target = getFixture();
    target.appendChild(sampleContent);
    target.style.maxHeight = `${contentHeight}px`;
    target.style.overflow = "auto";
    target.scrollTo({ top: 50 });
    await animationFrame();
    expect(".o_control_panel").toHaveClass("o_mobile_sticky", {
        message: "control panel becomes sticky when the target is not on top",
    });
    target.scrollTo({ top: -50 });
    await animationFrame();
    expect(".o_control_panel").not.toHaveClass("o_mobile_sticky", {
        message: "control panel is not sticky anymore",
    });
});

test.tags("mobile");
test("sticky scroll effect is not rebuilt on re-render", async () => {
    // The scroll useEffect must have explicit deps: a re-render must not re-run
    // its setup and reset root.el.style.top to "0px" while the panel is in its
    // translated-up sticky state.
    const cp = await mountWithSearch(ControlPanel, { resModel: "foo" });
    const contentHeight = 200;
    const sampleContent = document.createElement("div");
    sampleContent.style.minHeight = `${2 * contentHeight}px`;
    const target = getFixture();
    target.appendChild(sampleContent);
    target.style.maxHeight = `${contentHeight}px`;
    target.style.overflow = "auto";
    target.scrollTo({ top: 50 });
    await animationFrame();
    const panel = queryFirst(".o_control_panel");
    expect(panel).toHaveClass("o_mobile_sticky");
    const stickyTop = panel.style.top;
    expect(stickyTop).not.toBe("0px");

    // Force a re-render (as a pager/breadcrumb/count update would): the effect
    // must not re-run, so the sticky top offset survives.
    cp.render();
    await animationFrame();
    expect(panel.style.top).toBe(stickyTop);
    expect(panel).toHaveClass("o_mobile_sticky");
});
