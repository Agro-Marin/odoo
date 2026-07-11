// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { onMounted } from "@odoo/owl";
import {
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { GaugeField } from "@web/fields/display/gauge/gauge_field";

import { setupChartJsForTests } from "../graph/graph_test_helpers.js";

class Partner extends models.Model {
    int_field = fields.Integer({ string: "int_field" });
    another_int_field = fields.Integer({ string: "another_int_field" });
    _records = [
        { id: 1, int_field: 10, another_int_field: 45 },
        { id: 2, int_field: 4, another_int_field: 10 },
    ];
}

class User extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, User]);

setupChartJsForTests();

test("GaugeField in kanban view", async () => {
    // Capture each gauge's resolved max so we assert `max_field` is actually
    // honoured (a regression that read the wrong option key once shipped green
    // because this test only checked the displayed value, never the max).
    // Collected order-independently because kanban cards mount bottom-up.
    const maxes = [];
    patchWithCleanup(GaugeField.prototype, {
        setup() {
            super.setup();
            onMounted(() => {
                maxes.push(
                    this.chart.config.options.plugins.tooltip.callbacks.label({}),
                );
            });
        },
    });

    await mountView({
        type: "kanban",
        resModel: "partner",
        arch: /* xml */ `
        <kanban>
            <field name="another_int_field"/>
            <templates>
                <t t-name="card">
                    <field name="int_field" widget="gauge" options="{'max_field': 'another_int_field'}"/>
                </t>
            </templates>
        </kanban>`,
    });

    expect(".o_kanban_record:not(.o_kanban_ghost)").toHaveCount(2);
    expect(".o_field_widget[name=int_field] .oe_gauge canvas").toHaveCount(2);
    expect(queryAllTexts(".o_gauge_value")).toEqual(["10.0", "4.0"]);
    // max pulled from another_int_field (45, 10) — NOT the default of 100.
    expect(maxes.toSorted()).toEqual(["Max: 10.0", "Max: 45.0"]);
});

test("GaugeValue supports max_value option", async () => {
    patchWithCleanup(GaugeField.prototype, {
        setup() {
            super.setup();
            onMounted(() => {
                expect.step("gauge mounted");
                expect(
                    this.chart.config.options.plugins.tooltip.callbacks.label({}),
                ).toBe("Max: 120.0");
            });
        },
    });

    Partner._records = Partner._records.slice(0, 1);

    await mountView({
        type: "kanban",
        resModel: "partner",
        arch: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <div>
                            <field name="int_field" widget="gauge" options="{'max_value': 120}"/>
                        </div>
                    </t>
                </templates>
            </kanban>`,
    });

    expect.verifySteps(["gauge mounted"]);
    expect(".o_field_widget[name=int_field] .oe_gauge canvas").toHaveCount(1);
    expect(".o_gauge_value").toHaveText("10.0");
});

test("GaugeField renders large values in human-readable form", async () => {
    Partner._records = [{ id: 1, int_field: 1234567, another_int_field: 2000000 }];

    await mountView({
        type: "kanban",
        resModel: "partner",
        arch: /* xml */ `
        <kanban>
            <field name="another_int_field"/>
            <templates>
                <t t-name="card">
                    <field name="int_field" widget="gauge" options="{'max_field': 'another_int_field'}"/>
                </t>
            </templates>
        </kanban>`,
    });

    expect(".o_gauge_value").toHaveText("1.2M", {
        message: "the displayed value must use the human-readable formatter",
    });
});
