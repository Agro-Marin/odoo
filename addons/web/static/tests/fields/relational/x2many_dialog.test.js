// @ts-check

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
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { RelationalRecord } from "@web/model/relational_model/record";

describe.current.tags("desktop");

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

describe("dialog save", () => {
    test("saving a new record in the dialog adds it to the one2many list", async () => {
        onRpc("partner", "web_save", ({ args }) => {
            const turtleCommands = args[1].turtles;
            const creates = turtleCommands.filter((/** @type {any} */ c) => c[0] === 0);
            expect(creates).toHaveLength(1);
            expect(creates[0][2].name).toBe("michelangelo");
            expect.step("web_save");
        });

        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        await contains(".o_field_x2many_list_row_add a").click();
        await fieldInput("name").edit("michelangelo");

        await contains(".o_dialog .o_form_button_save").click();
        expect(".o_dialog").toHaveCount(0, { message: "dialog closed after save" });
        expect(".o_data_row").toHaveCount(2, { message: "two rows now in the list" });

        await clickSave();
        expect.verifySteps(["web_save"]);
    });
});

describe("dialog discard", () => {
    test("discarding the dialog leaves the one2many list unchanged", async () => {
        onRpc("partner", "web_save", () => {
            throw new Error("web_save should not be called");
        });

        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        expect(".o_data_row").toHaveCount(1);

        await contains(".o_field_x2many_list_row_add a").click();
        await fieldInput("name").edit("michelangelo");

        await contains(".o_dialog .btn-close").click();

        expect(".o_dialog").toHaveCount(0, { message: "dialog is closed" });
        expect(".o_data_row").toHaveCount(1, {
            message: "list still has only the original row",
        });
    });
});

describe("dialog title", () => {
    test("dialog title reads 'Create <relation_string>' for a new record", async () => {
        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        await contains(".o_field_x2many_list_row_add a").click();

        expect(".o_dialog .modal-title").toHaveText("Create Turtles");
    });
});

describe("shared archInfo", () => {
    test("dialog is not permanently readonly after an open on a readonly parent", async () => {
        let forceRootReadonly = false;
        patchWithCleanup(RelationalRecord.prototype, {
            get isInEdition() {
                if (forceRootReadonly && this === this.model?.root) {
                    return false;
                }
                return super.isInEdition;
            },
        });

        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        forceRootReadonly = true;
        await contains(".o_data_row .o_data_cell").click();
        expect(".o_dialog").toHaveCount(1);
        expect(".o_dialog .o_field_widget[name=name] input").toHaveCount(0, {
            message: "dialog form should be readonly",
        });
        await contains(".o_dialog .btn-close").click();
        expect(".o_dialog").toHaveCount(0);

        forceRootReadonly = false;
        await contains(".o_data_row .o_data_cell").click();
        expect(".o_dialog").toHaveCount(1);
        expect(".o_dialog .o_field_widget[name=name] input").toHaveCount(1, {
            message: "dialog form should be editable again",
        });
    });
});

describe("delete from list", () => {
    test("clicking the trash icon in the one2many list generates a DELETE command on parent save", async () => {
        onRpc("partner", "web_save", ({ args }) => {
            expect(args[1].turtles).toEqual([Command.delete(2)]);
            expect.step("web_save");
        });

        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

        await contains(".o_list_record_remove").click();

        expect(".o_data_row").toHaveCount(0);

        await clickSave();
        expect.verifySteps(["web_save"]);
    });
});
