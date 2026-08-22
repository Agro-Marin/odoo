import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Move extends models.Model {
    _name = "move";

    allowed = fields.Char();
    kind = fields.Selection({
        selection: [
            ["first", "First"],
            ["second", "Second"],
            ["third", "Third"],
        ],
    });

    _records = [
        { id: 1, kind: "first", allowed: "first,second" },
        { id: 2, kind: "first", allowed: "first, second" },
    ];
}

defineModels([Move]);

const ARCH = `
    <form>
        <field name="allowed" invisible="1"/>
        <field name="kind" widget="dynamic_selection" options="{'available_field': 'allowed'}"/>
    </form>`;

describe("DynamicSelection available options", () => {
    test("offers only the listed options", async () => {
        await mountView({ type: "form", resModel: "move", resId: 1, arch: ARCH });

        await contains("[name='kind'] .o_select_menu_toggler").click();

        expect(queryAllTexts(".o_select_menu_item")).toEqual(["First", "Second"]);
    });

    test("tolerates spaces after the separator", async () => {
        await mountView({ type: "form", resModel: "move", resId: 2, arch: ARCH });

        await contains("[name='kind'] .o_select_menu_toggler").click();

        expect(queryAllTexts(".o_select_menu_item")).toEqual(["First", "Second"]);
    });
});
