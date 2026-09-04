import { defineMrpModels } from "@mrp/../tests/mrp_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import {
    contains,
    defineActions,
    getService,
    mountWebClient,
    onRpc,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMrpModels();

defineActions([
    {
        id: 1,
        name: "MO Overview",
        tag: "mrp_mo_overview",
        target: "current",
        type: "ir.actions.client",
    },
]);

const OVERVIEW_HEADERS = "table[name=overview] thead th";

/**
 * Minimal payload of `report.mrp.report_mo_overview.get_report_values`: only
 * the summary line and the totals the footer reads.
 *
 * @param {string} state
 */
function reportValues(state) {
    return {
        data: {
            summary: {
                level: 0,
                name: "WH/MO/00001",
                state,
                formatted_state: "Draft",
                quantity: 1,
                unit_cost: 100,
                mo_cost: 100,
                bom_cost: 90,
                real_cost: 0,
                currency_id: 1,
            },
            components: [],
            operations: { summary: { index: "operations" }, details: [] },
            byproducts: { summary: { index: "byproducts" }, details: [] },
            extras: {
                unit_mo_cost: 100,
                unit_bom_cost: 90,
                unit_real_cost: 0,
            },
        },
        context: { show_uom: false },
    };
}

/** @param {string} state */
async function openMoOverview(state) {
    onRpc("get_report_values", () => reportValues(state));
    await mountWebClient();
    await getService("action").doAction(1, {
        additionalContext: { active_id: 1 },
    });
}

test("draft MO: the overview opens without the BoM Cost column", async () => {
    await openMoOverview("draft");
    expect(`${OVERVIEW_HEADERS}:contains(MO Cost)`).toHaveCount(1);
    expect(`${OVERVIEW_HEADERS}:contains(BoM Cost)`).toHaveCount(0);
});

test("confirmed MO: the overview opens without the BoM Cost column", async () => {
    await openMoOverview("confirmed");
    expect(`${OVERVIEW_HEADERS}:contains(MO Cost)`).toHaveCount(1);
    expect(`${OVERVIEW_HEADERS}:contains(BoM Cost)`).toHaveCount(0);
});

test("BoM Cost is still one click away in the Display filter", async () => {
    await openMoOverview("draft");
    await contains("button:contains(Display)").click();
    await contains(".o_menu_item:contains(BoM Costs)").click();
    expect(`${OVERVIEW_HEADERS}:contains(BoM Cost)`).toHaveCount(1);
});
