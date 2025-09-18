// @ts-check

/**
 * Integration tests for the X2ManyField component (one2many and many2many).
 *
 * Covers the core CRUD lifecycle — inline add/remove for one2many, and
 * link/unlink for many2many — and verifies the ORM command objects written
 * to web_save. Also tests that clicking a row in a non-editable one2many opens
 * the X2ManyFieldDialog.
 *
 * Module under test: fields/relational/x2many/x2many_field.js
 */

import { describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-mock";
import {
    clickFieldDropdown,
    clickFieldDropdownItem,
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
    timmy = fields.Many2many({ string: "Types", relation: "partner.type" });

    _records = [
        { id: 1, name: "first record", turtles: [2], timmy: [] },
        { id: 2, name: "second record", turtles: [], timmy: [12] },
    ];
}

class Turtle extends models.Model {
    name = fields.Char({ string: "Name" });
    turtle_foo = fields.Char({ string: "Foo" });
    turtle_trululu = fields.Many2one({ relation: "partner" });

    _records = [
        { id: 1, name: "leonardo", turtle_foo: "yop" },
        { id: 2, name: "donatello", turtle_foo: "blip" },
        { id: 3, name: "raphael", turtle_foo: "kawa" },
    ];

    _views = {
        form: `<form><field name="name"/><field name="turtle_foo"/></form>`,
    };
}

class PartnerType extends models.Model {
    name = fields.Char({ string: "Name" });

    _records = [
        { id: 12, name: "gold" },
        { id: 14, name: "silver" },
    ];

    _views = {
        form: `<form><field name="name"/></form>`,
        list: `<list><field name="name"/></list>`,
        search: `<search/>`,
    };
}

defineModels([Partner, Turtle, PartnerType]);

// ---------------------------------------------------------------------------
// One2many — inline CREATE / DELETE
// ---------------------------------------------------------------------------

describe("one2many inline CRUD", () => {
    test("adding a record inline generates a CREATE command on save", async () => {
        onRpc("partner", "web_save", ({ args }) => {
            // ORM encodes creates as [0, virtual_id, vals] — check by opcode + value
            const creates = args[1].turtles.filter((c) => c[0] === 0);
            expect(creates).toHaveLength(1);
            expect(creates[0][2].name).toBe("michelangelo");
            expect.step("web_save");
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `
                <form>
                    <field name="turtles">
                        <list editable="bottom">
                            <field name="name"/>
                        </list>
                    </field>
                </form>`,
        });

        await contains(".o_field_x2many_list_row_add a").click();
        // confirm: false avoids auto-Tab which would add a second empty row in the editable list
        await fieldInput("name").edit("michelangelo", { confirm: false });
        await clickSave();

        expect.verifySteps(["web_save"]);
    });

    test("removing a record from the inline list generates a DELETE command on save", async () => {
        onRpc("partner", "web_save", ({ args }) => {
            // partner 1 has turtles:[2]; removing it should generate DELETE(2)
            expect(args[1].turtles).toEqual([Command.delete(2)]);
            expect.step("web_save");
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `
                <form>
                    <field name="turtles">
                        <list editable="bottom">
                            <field name="name"/>
                        </list>
                    </field>
                </form>`,
        });

        await contains(".o_list_record_remove").click();
        await clickSave();

        expect.verifySteps(["web_save"]);
    });
});

// ---------------------------------------------------------------------------
// Many2many — LINK / UNLINK
// ---------------------------------------------------------------------------

describe("many2many LINK / UNLINK", () => {
    test("selecting a tag in many2many_tags generates a LINK command on save", async () => {
        onRpc("partner", "web_save", ({ args }) => {
            // Starting with no timmy; adding gold(12) → LINK(12)
            expect(args[1].timmy).toEqual([Command.link(12)]);
            expect.step("web_save");
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="timmy" widget="many2many_tags"/></form>`,
        });

        await clickFieldDropdown("timmy");
        await runAllTimers();
        await clickFieldDropdownItem("timmy", "gold");
        await clickSave();

        expect.verifySteps(["web_save"]);
    });

    test("removing a tag from many2many_tags generates an UNLINK command on save", async () => {
        onRpc("partner", "web_save", ({ args }) => {
            // record 2 starts with timmy:[12]; removing it → UNLINK(12)
            expect(args[1].timmy).toEqual([Command.unlink(12)]);
            expect.step("web_save");
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 2,
            arch: `<form><field name="timmy" widget="many2many_tags"/></form>`,
        });

        // Click the × button on the "gold" tag
        await contains(".o_field_many2many_tags .badge .o_delete").click();
        await clickSave();

        expect.verifySteps(["web_save"]);
    });
});

// ---------------------------------------------------------------------------
// Non-editable one2many — opens X2ManyFieldDialog
// ---------------------------------------------------------------------------

describe("dialog mode", () => {
    test("clicking Add a line in non-editable one2many opens X2ManyFieldDialog", async () => {
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `
                <form>
                    <field name="turtles">
                        <list>
                            <field name="name"/>
                        </list>
                        <form>
                            <field name="name"/>
                        </form>
                    </field>
                </form>`,
        });

        await contains(".o_field_x2many_list_row_add a").click();

        // X2ManyFieldDialog should be visible
        expect(".o_dialog").toHaveCount(1);
        expect(".o_dialog .o_form_view").toHaveCount(1);
    });
});
