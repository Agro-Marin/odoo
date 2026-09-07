import { describe, expect, test } from "@odoo/hoot";
import { registries } from "@odoo/o-spreadsheet";

const { pivotRegistry } = registries;

describe.current.tags("headless");

/**
 * `isMeasureCandidate` is consumed as a condition (`if (...)`), so it is its
 * truthiness that matters, not the value the `&&` chain happens to return.
 */
function isMeasureCandidate(field) {
    return Boolean(pivotRegistry.get("ODOO").isMeasureCandidate(field));
}

test("a non-stored field the server can aggregate is a measure candidate", () => {
    // `fields_get` only publishes `aggregator` once the server has proved it
    // can build the aggregate SQL for the field, so a non-stored field that
    // still carries one is aggregable: a stored related, or a compute whose
    // model overrides `_read_group_select` (stock.quant.value and friends).
    expect(
        isMeasureCandidate({
            name: "balance",
            type: "monetary",
            store: false,
            aggregator: "sum",
        })
    ).toBe(true);
});

test("a non-stored field the server refuses to aggregate is not a measure candidate", () => {
    // A pure compute: `fields_get` suppresses the aggregator, so the key is
    // absent from the payload the client sees.
    expect(
        isMeasureCandidate({
            name: "balance",
            type: "monetary",
            store: false,
        })
    ).toBe(false);
});

test("a stored measure field stays a measure candidate", () => {
    expect(
        isMeasureCandidate({
            name: "amount_total",
            type: "monetary",
            store: true,
            aggregator: "sum",
        })
    ).toBe(true);
});
