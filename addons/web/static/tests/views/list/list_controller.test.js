// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _name = "partner";

    name = fields.Char();

    _records = [
        { id: 1, name: "first" },
        { id: 2, name: "second" },
        { id: 3, name: "third" },
    ];
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

test.tags("desktop");
test("openRecord does not navigate when the dirty record fails validation", async () => {
    const listView = registry.category("views").get("list");
    class CustomListController extends listView.Controller {
        async openRecord(record) {
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
            expect.step(`navigate ${resId}`);
        },
    });

    await contains(`.o_data_cell`).click();
    await contains(`[name=name] input`).edit("");

    await contains(`td.o_list_record_open_form_view`).click();

    expect.verifySteps(["openRecord"]);
    expect(`.o_selected_row`).toHaveCount(1);
    expect(`.o_field_invalid`).toHaveCount(1);
});

test.tags("desktop");
test("onSelectionChanged fires for a cardinality-preserving selection swap", async () => {
    const seen = [];
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `<list><field name="name"/></list>`,
        allowSelectors: true,
        selectRecord: () => {},
        onSelectionChanged: (resIds) => seen.push(JSON.stringify(resIds)),
    });

    await contains(`.o_data_row:nth-child(1) .o_list_record_selector input`).click();
    await animationFrame();
    expect(seen.at(-1)).toBe("[1]");

    seen.length = 0;
    const inputs = document.querySelectorAll(
        `.o_data_row .o_list_record_selector input`,
    );
    inputs[0].click();
    inputs[1].click();
    await animationFrame();
    expect(seen.at(-1)).toBe("[2]");

    seen.length = 0;
    inputs[2].click();
    await animationFrame();
    expect(seen.at(-1)).toBe("[2,3]");
});

test.tags("desktop");
test("onSelectionChanged ignores a superseded resId resolution", async () => {
    const seen = [];
    let releaseFirst = null;
    let call = 0;
    patchWithCleanup(DynamicRecordList.prototype, {
        getResIds(selected) {
            const result = super.getResIds(selected);
            if (++call === 1) {
                return new Promise((resolve) => {
                    releaseFirst = () => resolve(result);
                });
            }
            return result;
        },
    });

    await mountView({
        resModel: "partner",
        type: "list",
        arch: `<list><field name="name"/></list>`,
        allowSelectors: true,
        selectRecord: () => {},
        onSelectionChanged: (resIds) => seen.push(JSON.stringify(resIds)),
    });

    const inputs = document.querySelectorAll(
        `.o_data_row .o_list_record_selector input`,
    );
    inputs[0].click();
    await animationFrame();
    inputs[1].click();
    await animationFrame();

    releaseFirst?.();
    await animationFrame();

    expect(seen.at(-1)).toBe("[1,2]");
});
