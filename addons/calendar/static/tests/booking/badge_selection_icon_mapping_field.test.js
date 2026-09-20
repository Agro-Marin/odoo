import { expect, test } from "@odoo/hoot";
import { waitFor } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

import { defineAppointmentModels } from "./appointment_tests_common.js";

class AppointmentQuestion extends models.Model {
    _name = "survey.question";

    question_type = fields.Selection({
        selection: [
            ["char", "Char"],
            ["checkbox", "Checkbox"],
            ["text", "Text"],
        ],
        default: "char",
    });
}
defineAppointmentModels();
defineModels([AppointmentQuestion]);

test("verify badges and their icon are correctly displayed", async () => {
    await mountView({
        type: "form",
        resModel: "survey.question",
        arch: `<form>
                <field name="question_type" widget="selection_badge_icon_mapping" options="{
                    'icon_mapping': {
                        'char': 'fa-times',
                        'checkbox': 'fa-check-square'
                    }
                }"/>
            </form>`,
    });
    await waitFor("div.o_field_selection_badge_icon_mapping");
    await waitFor("span.o_selection_badge.active:contains(Char)");

    await waitFor("span.o_selection_badge:contains(Char) span.fa-times");
    await waitFor("span.o_selection_badge:contains(Checkbox) span.fa-check-square");
    // Default icon is fa-check
    await waitFor("span.o_selection_badge:contains(Text) span.fa-check");
});

test("only supported embedded question types are offered", async () => {
    await mountView({
        type: "form",
        resModel: "survey.question",
        arch: `<form><field name="question_type" widget="selection_badge_icon_mapping"
            options="{'allowed_values': ['char', 'text']}"/></form>`,
    });
    expect(".o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge:contains(Checkbox)").toHaveCount(0);
});
