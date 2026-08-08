import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    lines = fields.One2many({ relation: "lines_sections" });
    _records = [
        {
            id: 1,
            lines: [1, 2],
        },
    ];
}

// The section label lives on `display_name`, exactly as it does on the real
// `resource.calendar.attendance` (see resource_calendar_attendance_views.xml).
// This fixture used to declare a `title` field instead, matching the renderer's
// `titleField = "title"` -- so the pair agreed with each other and with nothing
// else, and the test stayed green while every real section header rendered
// blank. A fixture that invents the field under test cannot catch this class of
// bug; mirroring the real model is the point.
class LinesSections extends models.Model {
    _name = "lines_sections";

    display_type = fields.Char();
    display_name = fields.Char();
    int = fields.Integer();

    _records = [
        {
            id: 1,
            display_type: "line_section",
            display_name: "firstSectionTitle",
            int: 4,
        },
        {
            id: 2,
            display_type: false,
            display_name: "recordTitle",
            int: 5,
        },
    ];
}

defineModels([Partner, LinesSections]);

const ARCH = `
    <form>
        <field name="lines" widget="section_one2many">
            <list>
                <field name="display_type" column_invisible="1" />
                <field name="display_name" />
                <field name="int" />
            </list>
        </field>
    </form>
`;

test("basic rendering", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });
    expect(".o_field_x2many .o_list_renderer table.o_section_list_view").toHaveCount(1);
    expect(".o_data_row").toHaveCount(2);
    expect(".o_data_row:first").toHaveClass("o_is_line_section fw-bold");
    expect(".o_data_row:eq(1)").not.toHaveClass("o_is_line_section fw-bold");
    expect(".o_data_row:first").toHaveText("firstSectionTitle");
    expect(".o_data_row:eq(1)").toHaveText("recordTitle 5");
    expect(".o_data_row:first td[name=display_name]").toHaveAttribute("colspan", "3");
    expect(".o_data_row:eq(1) td[name=display_name]").not.toHaveAttribute("colspan");
    expect(".o_list_record_remove").toHaveCount(1);
    expect(".o_is_line_section .o_list_record_remove").toHaveCount(0);
});

test("section row shows its label rather than an empty band", async () => {
    // The regression this locks down: a section header that renders as a blank
    // grey row because the renderer looked for a column that is not in the list.
    await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });
    expect(".o_data_row:first").toHaveText("firstSectionTitle");
    expect(".o_data_row:first").not.toHaveText("");
});
