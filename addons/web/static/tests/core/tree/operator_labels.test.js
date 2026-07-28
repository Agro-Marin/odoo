// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getOperatorLabel } from "@web/core/tree/operator_labels";

describe.current.tags("headless");

test("inherited Object.prototype keys are not treated as operators", () => {
    for (const key of ["toString", "valueOf", "hasOwnProperty"]) {
        const label = String(getOperatorLabel(key));
        expect(label).not.toInclude("[object");
        expect(label).not.toInclude("native code");
    }
    expect(String(getOperatorLabel("=", "char"))).toBe("is equal to");
});
