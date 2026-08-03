import { convertNumericToUnit, getHtmlStyle } from "@html_editor/utils/formatting";
import { expect, test } from "@odoo/hoot";

test("Convert with maximum float precision", () => {
    // The conversion can be off by exactly `Number.EPSILON`, and `toBeCloseTo`
    // requires a strictly smaller margin, hence `2 * Number.EPSILON`.
    expect(convertNumericToUnit(1400, "ms", "s")).toBeCloseTo(1.4, {
        margin: 2 * Number.EPSILON,
    });
    expect(convertNumericToUnit(19, "px", "rem", getHtmlStyle(document))).toBe(1.1875);
});
