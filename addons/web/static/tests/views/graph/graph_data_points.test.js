// @ts-check

/**
 * Pure unit tests for graph's data shaping.
 *
 * `GraphModel.loadDataPoints` was 195 lines sitting between two
 * `orm.formattedReadGroup` awaits, so every branch below — eight label shapes,
 * the many2one disambiguation counter, the cumulated-start fold and the
 * multi-currency fallback — was reachable only by mounting a webclient
 * (F-U12-2). `graph_data_points.js` extracts them; this file tests them as
 * functions, which is the shape `views/pivot` has had all along.
 *
 * Modules under test:
 *  - views/graph/graph_data_points.js
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    applyCurrencyFallback,
    foldCumulatedStart,
    getGroupCurrencies,
    getGroupLabels,
    getMeasureSpec,
    getRawValue,
    getValueLabel,
    makeDataPoint,
} from "@web/views/graph/graph_data_points";

const gb = (/** @type {string} */ fieldName, spec = fieldName) => ({
    fieldName,
    spec,
});
const noFilterLabel = () => "None";
const aggs = ["currency_id:array_agg_distinct", "amount:sum_currency"];

describe("getMeasureSpec", () => {
    test("__count needs no aggregate", () => {
        expect(getMeasureSpec("__count", {})).toEqual({
            measures: ["__count"],
            fieldAggregate: "__count",
            monetaryAggregates: undefined,
        });
    });

    test("a plain measure appends its aggregate after __count", () => {
        const fields = { amount: { name: "amount", type: "float", aggregator: "sum" } };
        expect(getMeasureSpec("amount", fields)).toEqual({
            measures: ["__count", "amount:sum"],
            fieldAggregate: "amount:sum",
            monetaryAggregates: undefined,
        });
    });

    test("many2one is forced to count_distinct, overriding the declared aggregator", () => {
        const fields = {
            user_id: { name: "user_id", type: "many2one", aggregator: "sum" },
        };
        expect(getMeasureSpec("user_id", fields).fieldAggregate).toBe(
            "user_id:count_distinct",
        );
    });

    test("a missing aggregator throws and names the measure", () => {
        const fields = { amount: { name: "amount", type: "float" } };
        expect(() => getMeasureSpec("amount", fields)).toThrow(
            /No aggregate function has been provided for the measure 'amount'/,
        );
    });

    test("monetary with a currency_field adds both currency aggregates before the measure", () => {
        const fields = {
            amount: {
                name: "amount",
                type: "monetary",
                aggregator: "sum",
                currency_field: "currency_id",
            },
        };
        const spec = getMeasureSpec("amount", fields);
        expect(spec.measures).toEqual([
            "__count",
            "currency_id:array_agg_distinct",
            "amount:sum_currency",
            "amount:sum",
        ]);
        expect(spec.monetaryAggregates).toEqual([
            "currency_id:array_agg_distinct",
            "amount:sum_currency",
        ]);
    });

    test("monetary without a currency_field stays a plain measure", () => {
        const fields = {
            amount: { name: "amount", type: "monetary", aggregator: "sum" },
        };
        expect(getMeasureSpec("amount", fields).monetaryAggregates).toBe(undefined);
    });
});

describe("getGroupCurrencies", () => {
    const aggs = ["currency_id:array_agg_distinct", "amount:sum_currency"];

    test("a group with no currencies at all yields none", () => {
        // array_agg_distinct returns false, not [], when nothing aggregated
        expect(
            getGroupCurrencies({ "currency_id:array_agg_distinct": false }, aggs),
        ).toEqual([]);
    });

    test("null entries are dropped so unset rows do not count as a currency", () => {
        const group = { "currency_id:array_agg_distinct": [null, 1, null] };
        expect(getGroupCurrencies(group, aggs)).toEqual([1]);
    });

    test("distinct currencies are kept", () => {
        const group = { "currency_id:array_agg_distinct": [1, 2] };
        expect(getGroupCurrencies(group, aggs)).toEqual([1, 2]);
    });
});

describe("foldCumulatedStart", () => {
    test("keys by the groupBy levels other than the sequential field", () => {
        const startGroups = [
            { "date:month": false, user_id: [7, "Al"], "amount:sum": 5 },
        ];
        const { cumulatedStartValue } = foldCumulatedStart(startGroups, {
            groupBy: [gb("date", "date:month"), gb("user_id")],
            sequentialField: "date",
            fieldAggregate: "amount:sum",
            graphCurrencies: new Set(),
        });
        // the key must match the main pass's JSON.stringify(rawValues.slice(1))
        expect(cumulatedStartValue).toEqual({ '[{"user_id":[7,"Al"]}]': 5 });
    });

    test("a single currency is recorded and the raw value kept", () => {
        const aggs = ["currency_id:array_agg_distinct", "amount:sum_currency"];
        const graphCurrencies = new Set();
        const { cumulatedStartValue } = foldCumulatedStart(
            [
                {
                    user_id: [7, "Al"],
                    "amount:sum": 5,
                    "amount:sum_currency": 50,
                    "currency_id:array_agg_distinct": [3],
                },
            ],
            {
                groupBy: [gb("date", "date:month"), gb("user_id")],
                sequentialField: "date",
                fieldAggregate: "amount:sum",
                monetaryAggregates: aggs,
                defaultCurrency: 1,
                graphCurrencies,
            },
        );
        expect([...graphCurrencies]).toEqual([3]);
        expect(cumulatedStartValue['[{"user_id":[7,"Al"]}]']).toBe(5);
    });

    test("more than one currency swaps in the converted value and the company currency", () => {
        const aggs = ["currency_id:array_agg_distinct", "amount:sum_currency"];
        const graphCurrencies = new Set();
        const { cumulatedStartValue, cumulatedStartConverted } = foldCumulatedStart(
            [
                {
                    user_id: [7, "Al"],
                    "amount:sum": 5,
                    "amount:sum_currency": 50,
                    "currency_id:array_agg_distinct": [3, 4],
                },
            ],
            {
                groupBy: [gb("date", "date:month"), gb("user_id")],
                sequentialField: "date",
                fieldAggregate: "amount:sum",
                monetaryAggregates: aggs,
                defaultCurrency: 1,
                graphCurrencies,
            },
        );
        const key = '[{"user_id":[7,"Al"]}]';
        expect([...graphCurrencies]).toEqual([1]);
        expect(cumulatedStartValue[key]).toBe(50);
        expect(cumulatedStartConverted[key]).toBe(50);
    });
});

describe("getValueLabel — branch order is load-bearing", () => {
    test("a false boolean reads 'false', NOT the falsy-value label", () => {
        const fields = { active: { type: "boolean" } };
        expect(getValueLabel(false, gb("active"), fields, {}, noFilterLabel)).toBe(
            "false",
        );
    });

    test("a false integer reads '0', NOT the falsy-value label", () => {
        const fields = { seq: { type: "integer" } };
        expect(getValueLabel(false, gb("seq"), fields, {}, noFilterLabel)).toBe("0");
    });

    test("any other false falls back to the falsy-value label", () => {
        const fields = { user_id: { type: "many2one" } };
        expect(getValueLabel(false, gb("user_id"), fields, {}, noFilterLabel)).toBe(
            "None",
        );
    });

    test("selection resolves to its label", () => {
        const fields = { state: { type: "selection", selection: [["a", "Draft"]] } };
        expect(getValueLabel("a", gb("state"), fields, {}, noFilterLabel)).toBe(
            "Draft",
        );
    });

    test("an unknown selection value stringifies rather than throwing", () => {
        const fields = { state: { type: "selection", selection: [["a", "Draft"]] } };
        expect(getValueLabel("zz", gb("state"), fields, {}, noFilterLabel)).toBe("zz");
    });

    test("date takes the formatted half of the pair", () => {
        const fields = { date: { type: "date" } };
        expect(
            getValueLabel(
                ["2026-08-01", "August 2026"],
                gb("date"),
                fields,
                {},
                noFilterLabel,
            ),
        ).toBe("August 2026");
    });

    test("anything else passes through untouched", () => {
        const fields = { name: { type: "char" } };
        expect(getValueLabel("Al", gb("name"), fields, {}, noFilterLabel)).toBe("Al");
    });
});

describe("getValueLabel — many2one disambiguation", () => {
    const fields = { user_id: { type: "many2one" } };

    test("two records sharing a name are numbered in first-seen order", () => {
        /** @type {import("@web/views/graph/graph_data_points").Numbering} */
        const numbering = {};
        const call = (/** @type {number} */ id, /** @type {string} */ name) =>
            getValueLabel([id, name], gb("user_id"), fields, numbering, noFilterLabel);
        expect(call(1, "Al")).toBe("Al");
        expect(call(2, "Al")).toBe("Al (2)");
        expect(call(3, "Al")).toBe("Al (3)");
    });

    test("the same record keeps its number when seen again", () => {
        /** @type {import("@web/views/graph/graph_data_points").Numbering} */
        const numbering = {};
        const call = (/** @type {number} */ id, /** @type {string} */ name) =>
            getValueLabel([id, name], gb("user_id"), fields, numbering, noFilterLabel);
        expect(call(1, "Al")).toBe("Al");
        expect(call(2, "Al")).toBe("Al (2)");
        expect(call(1, "Al")).toBe("Al");
    });

    test("different names are numbered independently", () => {
        /** @type {import("@web/views/graph/graph_data_points").Numbering} */
        const numbering = {};
        const call = (/** @type {number} */ id, /** @type {string} */ name) =>
            getValueLabel([id, name], gb("user_id"), fields, numbering, noFilterLabel);
        expect(call(1, "Al")).toBe("Al");
        expect(call(2, "Bo")).toBe("Bo");
    });

    test("the counter is per field, so the same name under another field restarts", () => {
        /** @type {import("@web/views/graph/graph_data_points").Numbering} */
        const numbering = {};
        const twoFields = {
            user_id: { type: "many2one" },
            partner_id: { type: "many2one" },
        };
        expect(
            getValueLabel(
                [1, "Al"],
                gb("user_id"),
                twoFields,
                numbering,
                noFilterLabel,
            ),
        ).toBe("Al");
        expect(
            getValueLabel(
                [2, "Al"],
                gb("partner_id"),
                twoFields,
                numbering,
                noFilterLabel,
            ),
        ).toBe("Al");
    });
});

describe("getGroupLabels", () => {
    test("collects a label and a raw value per groupBy level", () => {
        const fields = {
            name: { type: "char" },
            state: { type: "selection", selection: /** @type {any[]} */ ([]) },
        };
        const result = getGroupLabels(
            { name: "Al", state: "zz" },
            {
                groupBy: [gb("name"), gb("state")],
                fields,
                numbering: {},
                getDefaultFilterLabel: noFilterLabel,
            },
        );
        expect(result.labels).toEqual(["Al", "zz"]);
        expect(result.rawValues).toEqual([{ name: "Al" }, { state: "zz" }]);
    });

    test("a falsy x-axis group is flagged", () => {
        const fields = { user_id: { type: "many2one" } };
        const result = getGroupLabels(
            { user_id: false },
            {
                groupBy: [gb("user_id")],
                fields,
                numbering: {},
                getDefaultFilterLabel: noFilterLabel,
            },
        );
        expect(result.isFalsyXGroup).toBe(true);
    });

    test("a false BOOLEAN x-axis group is NOT flagged — false is a real category", () => {
        const fields = { active: { type: "boolean" } };
        const result = getGroupLabels(
            { active: false },
            {
                groupBy: [gb("active")],
                fields,
                numbering: {},
                getDefaultFilterLabel: noFilterLabel,
            },
        );
        expect(result.isFalsyXGroup).toBe(false);
        expect(result.labels).toEqual(["false"]);
    });

    test("a false INTEGER x-axis group is NOT flagged either", () => {
        const fields = { seq: { type: "integer" } };
        const result = getGroupLabels(
            { seq: false },
            {
                groupBy: [gb("seq")],
                fields,
                numbering: {},
                getDefaultFilterLabel: noFilterLabel,
            },
        );
        expect(result.isFalsyXGroup).toBe(false);
    });

    test("a falsy value below the x axis does not flag the group", () => {
        const fields = { name: { type: "char" }, user_id: { type: "many2one" } };
        const result = getGroupLabels(
            { name: "Al", user_id: false },
            {
                groupBy: [gb("name"), gb("user_id")],
                fields,
                numbering: {},
                getDefaultFilterLabel: noFilterLabel,
            },
        );
        expect(result.isFalsyXGroup).toBe(false);
        expect(result.labels).toEqual(["Al", "None"]);
    });

    test("numbering carries across groups, which is why it is passed in", () => {
        const fields = { user_id: { type: "many2one" } };
        /** @type {import("@web/views/graph/graph_data_points").Numbering} */
        const numbering = {};
        const params = {
            groupBy: [gb("user_id")],
            fields,
            numbering,
            getDefaultFilterLabel: noFilterLabel,
        };
        expect(getGroupLabels({ user_id: [1, "Al"] }, params).labels).toEqual(["Al"]);
        expect(getGroupLabels({ user_id: [2, "Al"] }, params).labels).toEqual([
            "Al (2)",
        ]);
    });
});

describe("applyCurrencyFallback", () => {
    const point = (over = {}) => ({
        value: 5,
        cumulatedStart: 1,
        convertedValue: 50,
        convertedCumulatedStart: 10,
        currencyId: 3,
        ...over,
    });

    test("a single-currency graph keeps its values", () => {
        const [p] = applyCurrencyFallback([point()], {
            graphCurrencies: new Set([3]),
            defaultCurrency: 1,
            hasMonetaryAggregates: true,
        });
        expect(p.value).toBe(5);
        expect(p.currencyId).toBe(3);
    });

    test("the converted scratch fields are always deleted", () => {
        const [p] = applyCurrencyFallback([point()], {
            graphCurrencies: new Set([3]),
            defaultCurrency: 1,
            hasMonetaryAggregates: true,
        });
        expect("convertedValue" in p).toBe(false);
        expect("convertedCumulatedStart" in p).toBe(false);
    });

    test("a mixed-currency graph falls back to the company currency and converted values", () => {
        const [p] = applyCurrencyFallback([point()], {
            graphCurrencies: new Set([3, 4]),
            defaultCurrency: 1,
            hasMonetaryAggregates: true,
        });
        expect(p.currencyId).toBe(1);
        expect(p.value).toBe(50);
        expect(p.cumulatedStart).toBe(10);
    });

    test("without monetary aggregates only the currency is reassigned", () => {
        const [p] = applyCurrencyFallback([point()], {
            graphCurrencies: new Set([3, 4]),
            defaultCurrency: 1,
            hasMonetaryAggregates: false,
        });
        expect(p.currencyId).toBe(1);
        expect(p.value).toBe(5);
    });
});

describe("getRawValue", () => {
    test("an empty group's false reads as 0", () => {
        expect(getRawValue({ "amount:sum": false }, "amount:sum")).toBe(0);
    });

    test("a real value passes through, including a genuine 0", () => {
        expect(getRawValue({ "amount:sum": 7.5 }, "amount:sum")).toBe(7.5);
        expect(getRawValue({ "amount:sum": 0 }, "amount:sum")).toBe(0);
    });
});

describe("makeDataPoint", () => {
    const base = {
        labels: ["Al", "Draft"],
        rawValues: [{ user_id: [7, "Al"] }, { state: "draft" }],
        isFalsyXGroup: false,
        fieldAggregate: "amount:sum",
        graphCurrencies: new Set(),
        cumulatedStartValue: {},
        cumulatedStartConverted: {},
    };

    test("carries the group's count, domain and value", () => {
        const p = makeDataPoint(
            { __count: 3, __domain: [["id", "=", 1]], "amount:sum": 12 },
            base,
        );
        expect(p.count).toBe(3);
        expect(p.domain).toEqual([["id", "=", 1]]);
        expect(p.value).toBe(12);
        expect(p.labels).toEqual(["Al", "Draft"]);
    });

    test("datasetId drops the x-axis level so a series spans its x values", () => {
        const p = makeDataPoint({ __count: 1, "amount:sum": 1 }, base);
        expect(p.datasetId).toBe('[{"state":"draft"}]');
        expect(p.xIdentifier).toBe('[{"user_id":[7,"Al"]}]');
        expect(p.identifier).toBe('[{"user_id":[7,"Al"]},{"state":"draft"}]');
    });

    test("cumulated start is looked up by datasetId, defaulting to 0", () => {
        const p = makeDataPoint(
            { __count: 1, "amount:sum": 1 },
            {
                ...base,
                cumulatedStartValue: { '[{"state":"draft"}]': 40 },
            },
        );
        expect(p.cumulatedStart).toBe(40);
        expect(
            makeDataPoint({ __count: 1, "amount:sum": 1 }, base).cumulatedStart,
        ).toBe(0);
    });

    test("a non-monetary point carries no currency", () => {
        const p = makeDataPoint({ __count: 1, "amount:sum": 1 }, base);
        expect("currencyId" in p).toBe(false);
    });

    test("a single-currency monetary point keeps its own currency and raw value", () => {
        const graphCurrencies = new Set();
        const p = makeDataPoint(
            {
                __count: 2,
                "amount:sum": 12,
                "amount:sum_currency": 120,
                "currency_id:array_agg_distinct": [3],
            },
            { ...base, monetaryAggregates: aggs, defaultCurrency: 1, graphCurrencies },
        );
        expect(p.currencyId).toBe(3);
        expect(p.value).toBe(12);
        expect([...graphCurrencies]).toEqual([3]);
    });

    test("a point spanning two currencies falls back to the company currency", () => {
        const graphCurrencies = new Set();
        const p = makeDataPoint(
            {
                __count: 2,
                "amount:sum": 12,
                "amount:sum_currency": 120,
                "currency_id:array_agg_distinct": [3, 4],
            },
            { ...base, monetaryAggregates: aggs, defaultCurrency: 1, graphCurrencies },
        );
        expect(p.currencyId).toBe(1);
        expect(p.value).toBe(120);
        expect([...graphCurrencies]).toEqual([1]);
    });

    test("an EMPTY group contributes no currency, so it cannot force multi-currency mode", () => {
        const graphCurrencies = new Set();
        makeDataPoint(
            {
                __count: 0,
                "amount:sum": false,
                "amount:sum_currency": 0,
                "currency_id:array_agg_distinct": [3],
            },
            { ...base, monetaryAggregates: aggs, defaultCurrency: 1, graphCurrencies },
        );
        expect([...graphCurrencies]).toEqual([]);
    });
});
