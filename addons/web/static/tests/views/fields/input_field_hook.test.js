// @ts-check

/**
 * Integration tests for the useInputField hook.
 *
 * The hook manages the dirty/clean lifecycle of text input fields: it sets
 * isDirty on each keystroke, commits on blur/Tab/Enter, and defers DOM updates
 * when the user is actively typing to prevent onchange rerenders from overwriting
 * user input mid-edit. All tests exercise the hook through a char or integer
 * field in a form view.
 *
 * Module under test: fields/input_field_hook.js
 */

import { describe, expect, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    clickSave,
    contains,
    defineModels,
    fieldInput,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

// ---------------------------------------------------------------------------
// Shared model definitions
// ---------------------------------------------------------------------------

class Partner extends models.Model {
    _name = "res.partner";
    _inherit = [];

    name = fields.Char({ string: "Name" });
    int_field = fields.Integer({ string: "Integer" });
    foo = fields.Char({ string: "Foo" });

    _records = [{ id: 1, name: "yop", int_field: 10, foo: "yop" }];
}

defineModels([Partner]);

// ---------------------------------------------------------------------------
// Commit via blur (onChange)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Commit via Tab key (onKeydown)
// ---------------------------------------------------------------------------

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

        // edit without confirm leaves the field dirty (no blur/Tab/Enter auto-sent)
        await fieldInput("name").edit("tab saved", { confirm: false });
        // Tab triggers onKeydown → commitChanges
        await press("Tab");
        await animationFrame();

        // Save without any further interaction; the Tab commit already sent the value
        await clickSave();
        expect.verifySteps(["web_save"]);
    });
});

// ---------------------------------------------------------------------------
// Commit via Enter key (onKeydown)
// ---------------------------------------------------------------------------

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

        // edit without confirm leaves the field dirty (no blur/Tab/Enter auto-sent)
        await fieldInput("name").edit("enter saved", { confirm: false });
        await press("Enter");
        await animationFrame();

        await clickSave();
        expect.verifySteps(["web_save"]);
    });
});

// ---------------------------------------------------------------------------
// Parse error — invalid value for integer field
// ---------------------------------------------------------------------------

describe("parse error handling", () => {
    test("typing a non-numeric value in an integer field marks the field invalid", async () => {
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="int_field"/></form>`,
        });

        // edit() fires input + change → onChange → parse throws → field marked invalid
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

        // The field is invalid: saving the form should surface a validation error,
        // not call web_save with the bad value.
        await contains(".o_form_button_save").click();

        expect(saveCalled).toBe(false, {
            message: "web_save must not be called while a field is invalid",
        });
        // Field must remain marked invalid (save was blocked)
        expect(".o_field_widget[name=int_field]").toHaveClass("o_field_invalid");
    });
});
