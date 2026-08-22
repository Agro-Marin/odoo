// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { mockDate, mockTimeZone } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { luxon } from "@web/core/l10n/luxon";
import { SearchArchParser } from "@web/search/search_arch_parser";
import { getPeriodOptions } from "@web/search/utils/dates";

describe.current.tags("headless");

const FIELDS = { d: { type: "date", string: "D" } };

function parseDateFilter(/** @type {string} */ attrs) {
    const parser = new SearchArchParser(
        { arch: `<search><filter name="f" date="d" ${attrs}/></search>` },
        FIELDS,
    );
    const { preSearchItems } = parser.parse();
    return preSearchItems[0][0];
}

describe("date filter period windows", () => {
    function optionsFor(/** @type {any} */ item) {
        mockTimeZone(0);
        mockDate("2020-06-01T13:00:00");
        return getPeriodOptions(luxon.DateTime.local(), item.optionsParams);
    }

    /** @type {[string, string, number][]} */
    const NON_INTEGER_CASES = [
        [`start_month="abc"`, "startMonth", -2],
        [`end_month="abc"`, "endMonth", 0],
        [`start_year="abc"`, "startYear", -2],
        [`end_year="abc"`, "endYear", 0],
        [`start_month="1.5"`, "startMonth", -2],
        [`end_year="2.5"`, "endYear", 0],
    ];

    test("an inverted month window is normalized with a warning", () => {
        patchWithCleanup(console, { warn: () => expect.step("warn") });

        const item = parseDateFilter(`start_month="2" end_month="-1"`);

        expect.verifySteps(["warn"]);
        expect(item.optionsParams.startMonth).toBe(-1);
        expect(item.optionsParams.endMonth).toBe(2);
        expect(item.defaultGeneratorIds).toEqual(["month"]);
    });

    test("an inverted YEAR window is normalized with a warning", () => {
        patchWithCleanup(console, { warn: () => expect.step("warn") });

        const item = parseDateFilter(`start_year="0" end_year="-3"`);

        expect.verifySteps(["warn"]);
        expect(item.optionsParams.startYear).toBe(-3);
        expect(item.optionsParams.endYear).toBe(0);
        expect(optionsFor(item).length).toBeGreaterThan(0);
    });

    test("a valid window is kept and the default offset is clamped into it", () => {
        const item = parseDateFilter(`start_month="-6" end_month="-3"`);

        expect(item.optionsParams.startMonth).toBe(-6);
        expect(item.optionsParams.endMonth).toBe(-3);
        expect(item.defaultGeneratorIds).toEqual(["month-3"]);
    });

    test("a non-integer bound falls back to its default, with a warning", () => {
        /** @type {string[]} */
        const warnings = [];
        patchWithCleanup(console, {
            warn: (/** @type {string} */ msg) => warnings.push(msg),
        });

        for (const [attrs, key, expected] of NON_INTEGER_CASES) {
            const item = parseDateFilter(attrs);
            expect(item.optionsParams[key]).toBe(expected);
            expect(optionsFor(item).length).toBeGreaterThan(0);
        }

        expect(warnings.length).toBe(NON_INTEGER_CASES.length);
        expect(warnings[0]).toMatch(/start_month="abc" is not a whole number/);
    });

    test("an implausibly wide window warns but is kept as declared", () => {
        patchWithCleanup(console, { warn: () => expect.step("warn") });

        const item = parseDateFilter(`start_year="-500"`);

        expect.verifySteps(["warn"]);
        expect(item.optionsParams.startYear).toBe(-500);
        expect(optionsFor(item).length).toBe(508);
    });
});

const FILTER_FIELDS = { bar: { type: "many2one", string: "Bar", relation: "partner" } };

describe("separator visibility", () => {
    function parseAroundSeparator(/** @type {string} */ invisible) {
        const parser = new SearchArchParser(
            {
                arch: `
                    <search>
                        <filter name="a" string="A" domain="[]"/>
                        <separator invisible="${invisible}"/>
                        <filter name="b" string="B" domain="[]"/>
                    </search>`,
            },
            FILTER_FIELDS,
        );
        return parser
            .parse()
            .preSearchItems.flat()
            .map((item) => item.groupNumber);
    }

    test("`invisible` never suppresses the split a separator performs", () => {
        const [a, b] = parseAroundSeparator("1");
        expect(a).not.toBe(b);
    });
});

describe("search panel field visibility", () => {
    function parsePanel(invisible, evalContext = {}) {
        const parser = new SearchArchParser(
            {
                arch: `
                    <search>
                        <searchpanel>
                            <field name="bar" invisible="${invisible}"/>
                        </searchpanel>
                    </search>`,
            },
            FILTER_FIELDS,
            {},
            {},
            evalContext,
        );
        return parser.parse().sections;
    }

    test("a literal invisible drops the section", () => {
        expect(parsePanel("1")).toHaveLength(0);
        expect(parsePanel("True")).toHaveLength(0);
    });

    test("a context expression drops the section when it holds", () => {
        expect(parsePanel("context.get('hide')", { hide: true })).toHaveLength(0);
        expect(parsePanel("context.get('hide')", {})).toHaveLength(1);
    });
});

describe("search panel category default", () => {
    function parseCategoryDefault(
        /** @type {Record<string, any>} */ searchPanelDefaults,
    ) {
        const parser = new SearchArchParser(
            { arch: `<search><searchpanel><field name="bar"/></searchpanel></search>` },
            FILTER_FIELDS,
            {},
            searchPanelDefaults,
        );
        const [[, section]] = parser.parse().sections;
        return section.activeValueId;
    }

    test("a scalar default is used as is", () => {
        expect(parseCategoryDefault({ bar: 7 })).toBe(7);
    });

    test("a list default collapses to its first entry", () => {
        expect(parseCategoryDefault({ bar: [7, 9] })).toBe(7);
    });
});

describe("field group numbers", () => {
    test("a <field> item carries a groupNumber like a <filter> does", () => {
        const parser = new SearchArchParser(
            {
                arch: `<search><field name="bar"/><filter name="a" string="A" domain="[]"/></search>`,
            },
            FILTER_FIELDS,
        );
        const items = parser.parse().preSearchItems.flat();
        expect(items.map((item) => typeof item.groupNumber)).toEqual([
            "number",
            "number",
        ]);
    });
});

describe("unknown field diagnostics", () => {
    test("a <field> naming an unknown field warns and is dropped, not silently vanished", () => {
        patchWithCleanup(console, {
            warn: (/** @type {string} */ msg) => expect.step(msg),
        });

        const parser = new SearchArchParser(
            { arch: `<search><field name="nope"/></search>` },
            FIELDS,
        );
        const items = parser.parse().preSearchItems.flat();

        expect(items).toEqual([]);
        expect.verifySteps([
            `[search] <field name="nope">: no such field on the model; the search field is ignored (check for a typo).`,
        ]);
    });

    test("a <filter date> naming an unknown field warns and is dropped", () => {
        patchWithCleanup(console, {
            warn: (/** @type {string} */ msg) => expect.step(msg),
        });

        const parser = new SearchArchParser(
            { arch: `<search><filter name="f" date="nope"/></search>` },
            FIELDS,
        );
        const items = parser.parse().preSearchItems.flat();

        expect(items).toEqual([]);
        expect.verifySteps([
            `[search] <filter date="nope">: no such field on the model; the date filter is ignored (check for a typo).`,
        ]);
    });
});
