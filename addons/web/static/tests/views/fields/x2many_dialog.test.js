// @ts-check

/**
 * Integration tests for the X2ManyFieldDialog component.
 *
 * Covers the dialog lifecycle: opening from a one2many field, saving a new
 * record, discarding changes, verifying the dialog title, and the delete flow.
 * All tests use a form view with a non-editable one2many field so that
 * clicking "Add a line" or a data row opens the X2ManyFieldDialog.
 *
 * Module under test: fields/relational/x2many_dialog.js
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    clickSave,
    Command,
    contains,
    defineModels,
    fieldInput,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

// ---------------------------------------------------------------------------
// Shared model definitions
// ---------------------------------------------------------------------------

class Partner extends models.Model {
    name = fields.Char();
    turtles = fields.One2many({
        string: "Turtles",
        relation: "turtle",
        relation_field: "turtle_trululu",
    });

    _records = [{ id: 1, name: "first record", turtles: [2] }];
}

class Turtle extends models.Model {
    name = fields.Char({ string: "Name" });
    turtle_foo = fields.Char({ string: "Foo" });
    turtle_trululu = fields.Many2one({ relation: "partner" });

    _records = [{ id: 2, name: "donatello", turtle_foo: "blip" }];
}

defineModels([Partner, Turtle]);

// ---------------------------------------------------------------------------
// Helper arch — a one2many field without editable so rows open in dialog
// ---------------------------------------------------------------------------
const ARCH = `
    <form>
        <field name="turtles">
            <list>
                <field name="name"/>
            </list>
            <form>
                <field name="name"/>
                <field name="turtle_foo"/>
            </form>
        </field>
    </form>`;

// ---------------------------------------------------------------------------
// Dialog open
// ---------------------------------------------------------------------------

describe("dialog open", () => {
    test("clicking Add a line opens the dialog with an empty form", async () => {
        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        await contains(".o_field_x2many_list_row_add a").click();

        expect(".o_dialog").toHaveCount(1, { message: "dialog should be visible" });
        expect(".o_dialog .o_field_widget[name=name] input").toHaveValue("");
    });

    test("clicking an existing row opens the dialog with that record's data", async () => {
        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        await contains(".o_data_row .o_data_cell").click();

        expect(".o_dialog").toHaveCount(1);
        expect(".o_dialog .o_field_widget[name=name] input").toHaveValue("donatello");
    });
});

// ---------------------------------------------------------------------------
// Dialog save
// ---------------------------------------------------------------------------

describe("dialog save", () => {
    test("saving a new record in the dialog adds it to the one2many list", async () => {
        onRpc("partner", "web_save", ({ args }) => {
            const turtleCommands = args[1].turtles;
            // Existing record (2) stays; new record is created
            const creates = turtleCommands.filter((c) => c[0] === 0);
            expect(creates).toHaveLength(1);
            expect(creates[0][2].name).toBe("michelangelo");
            expect.step("web_save");
        });

        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        await contains(".o_field_x2many_list_row_add a").click();
        await fieldInput("name").edit("michelangelo");

        // Save button inside the dialog
        await contains(".o_dialog .o_form_button_save").click();
        expect(".o_dialog").toHaveCount(0, { message: "dialog closed after save" });
        expect(".o_data_row").toHaveCount(2, { message: "two rows now in the list" });

        await clickSave();
        expect.verifySteps(["web_save"]);
    });
});

// ---------------------------------------------------------------------------
// Dialog discard
// ---------------------------------------------------------------------------

describe("dialog discard", () => {
    test("discarding the dialog leaves the one2many list unchanged", async () => {
        onRpc("partner", "web_save", () => {
            throw new Error("web_save should not be called");
        });

        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        // One existing row before opening the dialog
        expect(".o_data_row").toHaveCount(1);

        await contains(".o_field_x2many_list_row_add a").click();
        await fieldInput("name").edit("michelangelo");

        // Dismiss the dialog via the Close (×) button
        await contains(".o_dialog .btn-close").click();

        expect(".o_dialog").toHaveCount(0, { message: "dialog is closed" });
        expect(".o_data_row").toHaveCount(1, {
            message: "list still has only the original row",
        });
    });
});

// ---------------------------------------------------------------------------
// Dialog title
// ---------------------------------------------------------------------------

describe("dialog title", () => {
    test("dialog title reads 'Create <relation_string>' for a new record", async () => {
        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        await contains(".o_field_x2many_list_row_add a").click();

        // Title includes the one2many field's string ("Turtles")
        expect(".o_dialog .modal-title").toHaveText("Create Turtles");
    });
});

// ---------------------------------------------------------------------------
// Delete from dialog
// ---------------------------------------------------------------------------

describe("delete from list", () => {
    test("clicking the trash icon in the one2many list generates a DELETE command on parent save", async () => {
        onRpc("partner", "web_save", ({ args }) => {
            expect(args[1].turtles).toEqual([Command.delete(2)]);
            expect.step("web_save");
        });

        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        // Click the trash icon in the list row (one2many always shows delete per row)
        await contains(".o_list_record_remove").click();

        // Row removed from list
        expect(".o_data_row").toHaveCount(0);

        await clickSave();
        expect.verifySteps(["web_save"]);
    });
});
