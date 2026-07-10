// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

// Dedicated file (mirroring `list_controller.js`) to avoid colliding with
// the concurrently-edited `list_view.test.js`.

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _name = "partner";

    name = fields.Char();

    _records = [
        { id: 1, name: "first" },
        { id: 2, name: "second" },
    ];
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

test.tags("desktop");
test("openRecord does not navigate when the dirty record fails validation", async () => {
    const listView = registry.category("views").get("list");
    class CustomListController extends listView.Controller {
        async openRecord(record) {
            // Confirm openRecord is actually reached (rather than the click
            // being swallowed elsewhere), so this really exercises the guard.
            expect.step("openRecord");
            return super.openRecord(record);
        }
    }
    registry
        .category("views")
        .add(
            "custom_list",
            { ...listView, Controller: CustomListController },
            { force: true },
        );

    await mountView({
        resModel: "partner",
        type: "list",
        arch: `
            <list js_class="custom_list" editable="top" open_form_view="1">
                <field name="name" required="1"/>
            </list>`,
        selectRecord(resId) {
            // Navigation to the form view. Must NOT happen for an invalid,
            // unsaved record.
            expect.step(`navigate ${resId}`);
        },
    });

    // Make the first row dirty AND invalid by clearing the required field.
    await contains(`.o_data_cell`).click();
    await contains(`[name=name] input`).edit("");

    // Attempt to open the record: record.save() fails validation and returns
    // false, so openRecord must bail out before navigating.
    await contains(`td.o_list_record_open_form_view`).click();

    // openRecord ran, but no navigation happened, and we stay on the invalid
    // row (still selected/editable).
    expect.verifySteps(["openRecord"]);
    expect(`.o_selected_row`).toHaveCount(1);
    expect(`.o_field_invalid`).toHaveCount(1);
});
