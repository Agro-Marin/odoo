// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { extractInfoFromGroupData } from "@web/model/relational_model/field_values";

describe.current.tags("headless");

const selectionField = {
    name: "state",
    type: "selection",
    selection: [
        ["draft", "Draft"],
        ["done", "Done"],
    ],
};

function makeGroupInfo(field, rawValue) {
    return extractInfoFromGroupData(
        { __count: 1, __extra_domain: [], [field.name]: rawValue },
        [field.name],
        { [field.name]: field },
        [],
    );
}

test("selection group with a valid value uses the selection label", () => {
    const info = makeGroupInfo(selectionField, "done");
    expect(info.displayName).toBe("Done");
});

test("selection group with a falsy value falls back to 'None'", () => {
    const info = makeGroupInfo(selectionField, false);
    // Regression: previously returned ``undefined`` (Object.fromEntries lookup
    // miss) instead of the falsy label like every other field type.
    expect(info.displayName).toBe("None");
});

test("selection group with a falsy value honors falsy_value_label", () => {
    const info = makeGroupInfo(
        { ...selectionField, falsy_value_label: "Not set" },
        false,
    );
    expect(info.displayName).toBe("Not set");
});
