// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getOperatorLabel } from "@web/core/tree/operator_labels";

describe.current.tags("headless");

test("inherited Object.prototype keys are not treated as operators", () => {
    // `operator in OPERATOR_DESCRIPTIONS` matched inherited keys like
    // "toString"/"valueOf", so getOperatorLabel invoked the Object.prototype
    // function and returned junk like "[object Undefined]". Object.hasOwn
    // confines the lookup to real operators, so these fall through to
    // formatValue and render as a plain quoted literal instead.
    for (const key of ["toString", "valueOf", "hasOwnProperty"]) {
        const label = String(getOperatorLabel(key));
        expect(label).not.toInclude("[object");
        expect(label).not.toInclude("native code");
    }
    // A genuine operator still resolves to its human label.
    expect(String(getOperatorLabel("=", "char"))).toBe("is equal to");
});
