// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    clickSave,
    contains,
    defineModels,
    fieldInput,
    fields,
    makeServerError,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
import { applyFieldDirtyPayload } from "@web/fields/field_dirty_signal";
import { standardFieldProps } from "@web/fields/standard_field_props";

class Partner extends models.Model {
    _name = "res.partner";
    /** @type {string[]} */
    _inherit = [];

    name = fields.Char({ string: "Name" });
    int_field = fields.Integer({ string: "Integer" });
    foo = fields.Char({ string: "Foo" });

    _records = [{ id: 1, name: "yop", int_field: 10, foo: "yop" }];
}

defineModels([Partner]);

describe("blur commits value", () => {
    test("editing a char field and saving sends the new value to web_save", async () => {
        onRpc("res.partner", "web_save", ({ args }) => {
            expect(args[1].name).toBe("new value");
            expect.step("web_save");
        });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });
        await fieldInput("name").edit("new value");
        await clickSave();

        expect.verifySteps(["web_save"]);
    });

    test("clearing a char field saves false to the model (Odoo empty-string convention)", async () => {
        onRpc("res.partner", "web_save", ({ args }) => {
            expect(args[1].name).toBe(false);
            expect.step("web_save");
        });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });
        await fieldInput("name").clear();
        await clickSave();

        expect.verifySteps(["web_save"]);
    });
});

describe("Tab key commits value", () => {
    test("pressing Tab after filling commits the value before explicit save", async () => {
        onRpc("res.partner", "web_save", ({ args }) => {
            expect(args[1].name).toBe("tab saved");
            expect.step("web_save");
        });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/><field name="foo"/></form>`,
        });

        await fieldInput("name").edit("tab saved", { confirm: false });
        await press("Tab");
        await animationFrame();

        await clickSave();
        expect.verifySteps(["web_save"]);
    });
});

describe("Enter key commits value", () => {
    test("pressing Enter after filling commits the value in a char input", async () => {
        onRpc("res.partner", "web_save", ({ args }) => {
            expect(args[1].name).toBe("enter saved");
            expect.step("web_save");
        });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });

        await fieldInput("name").edit("enter saved", { confirm: false });
        await press("Enter");
        await animationFrame();

        await clickSave();
        expect.verifySteps(["web_save"]);
    });
});

describe("parse error handling", () => {
    test("typing a non-numeric value in an integer field marks the field invalid", async () => {
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="int_field"/></form>`,
        });

        await fieldInput("int_field").edit("not a number");

        expect(".o_field_widget[name=int_field]").toHaveClass("o_field_invalid", {
            message: "field should be marked invalid after an unparseable value",
        });
    });

    test("an invalid parse error does not update the model value", async () => {
        let saveCalled = false;
        onRpc("res.partner", "web_save", () => {
            saveCalled = true;
        });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="int_field"/></form>`,
        });

        await fieldInput("int_field").edit("abc");

        await contains(".o_form_button_save").click();

        expect(saveCalled).toBe(false, {
            message: "web_save must not be called while a field is invalid",
        });
        expect(".o_field_widget[name=int_field]").toHaveClass("o_field_invalid");
    });
});

describe("blur/Tab no-write on parse-equal re-entry", () => {
    test("blur: a dirty-but-parse-equal integer re-entry commits nothing", async () => {
        onRpc("res.partner", "web_save", () => expect.step("web_save"));
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="int_field"/></form>`,
        });
        await fieldInput("int_field").edit(" 10 ");
        await animationFrame();
        expect(".o_field_widget[name=int_field] input").toHaveValue("10");
        expect.verifySteps([]);
    });

    test("blur: a parse-equal re-entry re-emits FIELD_IS_DIRTY(false) and clears the save indicator", async () => {
        const dirtyEvents = [];
        class DirtySpy extends Component {
            static template = xml`<span class="o_dirty_spy"/>`;
            static props = { ...standardFieldProps };
            setup() {
                useBus(this.props.record.model.bus, "FIELD_IS_DIRTY", (ev) =>
                    dirtyEvents.push(ev.detail),
                );
            }
        }
        registry
            .category("fields")
            .add("dirty_spy_parse_equal", { component: DirtySpy });

        onRpc("res.partner", "web_save", () => expect.step("web_save"));
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form>
                <field name="int_field"/>
                <field name="foo" widget="dirty_spy_parse_equal"/>
            </form>`,
        });

        expect(".o_form_status_indicator_buttons").toHaveClass("invisible", {
            message: "pristine form: save/discard indicator hidden",
        });

        await fieldInput("int_field").edit(" 10 ");
        await animationFrame();

        expect(".o_field_widget[name=int_field] input").toHaveValue("10");
        expect.verifySteps([]);
        expect(dirtyEvents.length > 0).toBe(true, {
            message: "typing must have emitted FIELD_IS_DIRTY events",
        });
        expect(dirtyEvents.reduce(applyFieldDirtyPayload, new Set()).size).toBe(0, {
            message:
                "the parse-equal commit must leave no field reporting dirty; otherwise the indicator stays stuck on unsaved",
        });
        expect(".o_form_status_indicator_buttons").toHaveClass("invisible", {
            message:
                "nothing was committed, so the save/discard indicator must be hidden again",
        });
    });

    test("Tab: a dirty-but-parse-equal integer re-entry commits nothing (same as blur)", async () => {
        onRpc("res.partner", "web_save", () => expect.step("web_save"));
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="int_field"/><field name="foo"/></form>`,
        });
        await fieldInput("int_field").edit(" 10 ", { confirm: false });
        await press("Tab");
        await animationFrame();
        expect.verifySteps([]);
        expect(".o_field_widget[name=int_field] input").toHaveValue("10");
    });
});

describe("rejected update clears dirty-typing signal", () => {
    test("a rejected onchange still emits FIELD_IS_DIRTY(false) (try/finally guard)", async () => {
        expect.errors(1);

        const dirtyEvents = [];
        class DirtySpy extends Component {
            static template = xml`<span class="o_dirty_spy"/>`;
            static props = { ...standardFieldProps };
            setup() {
                useBus(this.props.record.model.bus, "FIELD_IS_DIRTY", (ev) =>
                    dirtyEvents.push(ev.detail),
                );
            }
        }
        registry.category("fields").add("dirty_spy", { component: DirtySpy });

        Partner._onChanges = {
            name: () => {
                throw makeServerError({ type: "ValidationError", message: "boom" });
            },
        };

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/><field name="foo" widget="dirty_spy"/></form>`,
        });

        await fieldInput("name").edit("boom");
        await animationFrame();

        expect.verifyErrors([/RPC_ERROR/]);
        expect(dirtyEvents.length > 0).toBe(true, {
            message: "editing must have emitted FIELD_IS_DIRTY events",
        });
        expect(dirtyEvents.reduce(applyFieldDirtyPayload, new Set()).size).toBe(0, {
            message: "no field may still report dirty after a rejected update",
        });
    });
});

describe("urgent commit racing an in-flight update", () => {
    test("an urgent commit writes what the user typed, even mid-flight", async () => {
        /** @type {any[]} */
        const updates = [];
        let bus = null;

        class UpdateSpy extends Component {
            static template = xml`<span/>`;
            static props = { ...standardFieldProps };
            setup() {
                bus = this.props.record.model.bus;
                const record = this.props.record;
                if (!record.__updateSpy) {
                    record.__updateSpy = true;
                    const update = record.update.bind(record);
                    record.update = (changes, options) => {
                        updates.push({ ...changes });
                        return update(changes, options);
                    };
                }
            }
        }
        registry.category("fields").add("update_spy", { component: UpdateSpy });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form>
                     <field name="name"/>
                     <field name="foo" widget="update_spy"/>
                   </form>`,
        });

        await fieldInput("name").edit("typed", { confirm: false });
        const proms = [];
        bus.trigger("NEED_LOCAL_CHANGES", { proms });
        bus.trigger("WILL_SAVE_URGENTLY", { proms });
        await Promise.all(proms);
        await animationFrame();

        expect(updates).toEqual([{ name: "typed" }, { name: "typed" }]);
    });

    test("an urgent commit settles even while an onchange never answers", async () => {
        let bus = null;
        const neverAnswers = new Deferred();
        onRpc("res.partner", "onchange", () => neverAnswers);

        class BusGrabber extends Component {
            static template = xml`<span/>`;
            static props = { ...standardFieldProps };
            setup() {
                bus = this.props.record.model.bus;
            }
        }
        registry.category("fields").add("bus_grabber", { component: BusGrabber });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form>
                     <field name="name"/>
                     <field name="foo" widget="bus_grabber"/>
                   </form>`,
        });

        await fieldInput("name").edit("typed", { confirm: false });

        const pending = [];
        bus.trigger("NEED_LOCAL_CHANGES", { proms: pending });
        const urgent = [];
        bus.trigger("WILL_SAVE_URGENTLY", { proms: urgent });

        let settled = false;
        Promise.all(urgent).then(() => {
            settled = true;
        });
        await animationFrame();

        expect(settled).toBe(true, {
            message:
                "the urgent handlers must hand over what is known, not wait on the network",
        });
    });
});
