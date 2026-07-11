// @ts-check

/**
 * Pure unit tests for the date-filter period window handling of
 * search/search_arch_parser.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { SearchArchParser } from "@web/search/search_arch_parser";

describe.current.tags("headless");

const FIELDS = { d: { type: "date", string: "D" } };

/** Parse a single date filter node and return its pre-search item. */
function parseDateFilter(attrs) {
    const parser = new SearchArchParser(
        { arch: `<search><filter name="f" date="d" ${attrs}/></search>` },
        FIELDS,
    );
    const { preSearchItems } = parser.parse();
    return preSearchItems[0][0];
}

describe("date filter month window", () => {
    test("an inverted month window is normalized with a warning", () => {
        patchWithCleanup(console, { warn: () => expect.step("warn") });

        const item = parseDateFilter(`start_month="2" end_month="-1"`);

        expect.verifySteps(["warn"]);
        expect(item.optionsParams.startMonth).toBe(-1);
        expect(item.optionsParams.endMonth).toBe(2);
        // Offset 0 is inside the normalized window → current month default.
        expect(item.defaultGeneratorIds).toEqual(["month"]);
    });

    test("a valid window is kept and the default offset is clamped into it", () => {
        const item = parseDateFilter(`start_month="-6" end_month="-3"`);

        expect(item.optionsParams.startMonth).toBe(-6);
        expect(item.optionsParams.endMonth).toBe(-3);
        expect(item.defaultGeneratorIds).toEqual(["month-3"]);
    });
});
