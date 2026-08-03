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
        expect(item.defaultGeneratorIds).toEqual(["month"]);
    });

    test("a valid window is kept and the default offset is clamped into it", () => {
        const item = parseDateFilter(`start_month="-6" end_month="-3"`);

        expect(item.optionsParams.startMonth).toBe(-6);
        expect(item.optionsParams.endMonth).toBe(-3);
        expect(item.defaultGeneratorIds).toEqual(["month-3"]);
    });
});

const FILTER_FIELDS = { bar: { type: "many2one", string: "Bar", relation: "partner" } };

describe("separator visibility", () => {
    /** groupIds of `a` and `b` in an arch whose middle separator carries `invisible`. */
    function parseAroundSeparator(invisible) {
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
        // 44 shipped search views put `<separator invisible="1"/>` in the middle
        // of the Activities block. That split is what makes
        // search_default_filter_activities_my AND with
        // search_default_activities_overdue rather than OR with it — honouring
        // the attribute rewrites those production domains. See
        // search_model.test.js, "the Activities block ANDs across …".
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
    function parseCategoryDefault(searchPanelDefaults) {
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
            FIELDS, // only "d" exists
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
            FIELDS, // only "d" exists
        );
        const items = parser.parse().preSearchItems.flat();

        expect(items).toEqual([]);
        expect.verifySteps([
            `[search] <filter date="nope">: no such field on the model; the date filter is ignored (check for a typo).`,
        ]);
    });
});
