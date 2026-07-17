// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    _name = "res.partner";

    name = fields.Char();
    int_field = fields.Integer();

    _records = [
        {
            id: 1,
            name: "partnerName",
            int_field: 0,
        },
    ];

    _views = {
        form: /* xml */ `
            <form>
                <group>
                    <field name="int_field" widget="color_picker"/>
                </group>
            </form>
        `,
        list: /* xml */ `
            <list>
                <field name="int_field" widget="color_picker"/>
                <field name="display_name" />
            </list>`,
    };
}

class User extends models.Model {
    _name = "res.users";

    name = fields.Char();

    has_group() {
        return true;
    }
}

defineModels([Partner, User]);

test("No chosen color is a red line with a white background (color 0)", async () => {
    await mountView({ type: "form", resModel: "res.partner", resId: 1 });

    expect(".o_field_color_picker button.o_colorlist_item_color_0").toHaveCount(1);
    await contains(".o_field_color_picker button").click();
    expect(".o_field_color_picker button.o_colorlist_item_color_0").toHaveCount(1);
    await contains(".o_field_color_picker .o_colorlist_item_color_3").click();
    await contains(".o_field_color_picker button").click();
    expect(".o_field_color_picker button.o_colorlist_item_color_0").toHaveCount(1);
});

test("closes when color selected or outside click", async () => {
    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: `
        <form>
            <group>
                <field name="int_field" widget="color_picker"/>
                <field name="name"/>
            </group>
        </form>`,
    });
    await contains(".o_field_color_picker button").click();
    expect(queryAll(".o_field_color_picker button").length).toBeGreaterThan(1);
    await contains(".o_field_color_picker .o_colorlist_item_color_3").click();
    expect(".o_field_color_picker button").toHaveCount(1);
    await contains(".o_field_color_picker button").click();
    await contains(".o_field_widget[name='name'] input").click();
    expect(".o_field_color_picker button").toHaveCount(1);
});

test("color picker on list view", async () => {
    await mountView({
        type: "list",
        resModel: "res.partner",
        selectRecord() {
            expect.step("record selected to open");
        },
    });

    await contains(".o_field_color_picker button").click();
    expect.verifySteps(["record selected to open"]);
});

test("color picker in editable list view", async () => {
    Partner._records.push({
        int_field: 1,
    });
    await mountView({
        type: "list",
        resModel: "res.partner",
        arch: `
            <list editable="bottom">
                <field name="int_field" widget="color_picker"/>
                <field name="display_name" />
            </list>`,
    });

    expect(".o_data_row:nth-child(1) .o_field_color_picker button").toHaveCount(1);
    await contains(".o_data_row:nth-child(1) .o_field_color_picker button").click();
    expect(".o_data_row:nth-child(1).o_selected_row").toHaveCount(1);
    expect(".o_data_row:nth-child(1) .o_field_color_picker button").toHaveCount(12);
    await contains(
        ".o_data_row:nth-child(1) .o_field_color_picker .o_colorlist_item_color_6",
    ).click();
    expect(".o_data_row:nth-child(1) .o_field_color_picker button").toHaveCount(12);
    await contains(".o_data_row:nth-child(2) .o_data_cell").click();
    expect(".o_data_row:nth-child(1) .o_field_color_picker button").toHaveCount(1);
    expect(".o_data_row:nth-child(2) .o_field_color_picker button").toHaveCount(12);
});

test("column widths: dont overflow color picker in list", async () => {
    Partner._fields.date_field = fields.Date({ string: "Date field" });
    await mountView({
        type: "list",
        resModel: "res.partner",
        arch: `
        <list editable="top">
            <field name="date_field"/>
            <field name="int_field" widget="color_picker"/>
        </list>`,
        domain: [["id", "<", 0]],
    });
    await contains(".o_control_panel_main_buttons .o_list_button_add", {
        visible: false,
    }).click();
    const date_column_width = queryAll(
        '.o_list_table thead th[data-name="date_field"]',
    )[0].style.width.replace("px", "");
    const int_field_column_width = queryAll(
        '.o_list_table thead th[data-name="int_field"]',
    )[0].style.width.replace("px", "");
    // Default widths: date ~92px, integer ~74px. Without `widthInList: '1'` on
    // the color_picker, int_field would stay narrower than date as the screen
    // grows; with it, int_field ends up wider.
    expect(parseFloat(date_column_width)).toBeLessThan(
        parseFloat(int_field_column_width),
        {
            message: "colorpicker should display properly (Horizontly)",
        },
    );
});

test("kanban_color_picker highlights the active color on a non-'color' field", async () => {
    // The widget writes to props.name (here int_field) but the active-swatch
    // highlight must read the same field, not a hardcoded `color`. Studio
    // generates this widget on arbitrary fields (e.g. x_color).
    Partner._records[0].int_field = 3;
    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: /* xml */ `<form><field name="int_field" widget="kanban_color_picker"/></form>`,
    });
    expect(".o_kanban_colorpicker .o_colorlist_item_color_3.active").toHaveCount(1, {
        message: "the swatch for the field's current value must be active",
    });
});
