// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    makeMockServer,
    MockServer,
    models,
} from "@web/../tests/web_test_helpers";

describe.current.tags("headless");

/**
 * The mock server is a second implementation of the ORM, and 1300+ files
 * outside `web` assert against it. Where it disagrees with the real one, a
 * suite is green about behaviour production does not have.
 *
 * `formatted_read_group` is the richest of those surfaces: it buckets dates and
 * labels the buckets, and both halves are locale-dependent. Every expectation
 * below is what the SERVER answered for `RECORDS` on `res.currency.rate` —
 * chosen because `name` (Date), `rate` (Float) and the model itself are all in
 * `base`, so the corpus regenerates on any database.
 *
 * Ten of the twelve granularities agree exactly. The two that do not are in
 * KNOWN_DIVERGENCES, which is a ratchet like the one in
 * `core/domain_server_parity.test.js`: a NEW divergence and a FIXED one both
 * fail here.
 *
 * To regenerate: create RECORDS on `res.currency.rate`, then for each
 * granularity `g` read
 * `formatted_read_group(domain, [f"name:{g}"], ["rate:sum", "__count"])`
 * and keep `[group[f"name:{g}"], group["rate:sum"], group["__count"]]`.
 * Language matters: these were generated under `week_start = 7`, which is both
 * the server default and `MockServer._lang_parameters.week_start`.
 */

class CurrencyRate extends models.Model {
    _name = "res.currency.rate";

    name = fields.Date();
    rate = fields.Float();

    _records = [
        { id: 1, name: "2024-01-01", rate: 1.0 }, // Monday, ISO week 1
        { id: 2, name: "2024-01-05", rate: 2.0 },
        { id: 3, name: "2024-01-07", rate: 3.0 }, // Sunday — the week boundary
        { id: 4, name: "2024-01-08", rate: 4.0 },
        { id: 5, name: "2024-03-31", rate: 5.0 }, // Sunday, quarter boundary
        { id: 6, name: "2024-04-01", rate: 6.0 },
        { id: 7, name: "2024-12-30", rate: 7.0 }, // week spanning the year end
        { id: 8, name: "2025-01-02", rate: 8.0 },
    ];
}

defineModels([CurrencyRate]);

/**
 * Server truth: granularity -> [[groupValue, rate:sum, __count], ...].
 * @type {Record<string, [any, number, number][]>}
 */
const SERVER = {
    day: [
        [["2024-01-01", "01 Jan 2024"], 1.0, 1],
        [["2024-01-05", "05 Jan 2024"], 2.0, 1],
        [["2024-01-07", "07 Jan 2024"], 3.0, 1],
        [["2024-01-08", "08 Jan 2024"], 4.0, 1],
        [["2024-03-31", "31 Mar 2024"], 5.0, 1],
        [["2024-04-01", "01 Apr 2024"], 6.0, 1],
        [["2024-12-30", "30 Dec 2024"], 7.0, 1],
        [["2025-01-02", "02 Jan 2025"], 8.0, 1],
    ],
    week: [
        [["2023-12-31", "W1 2024"], 3.0, 2],
        [["2024-01-07", "W2 2024"], 7.0, 2],
        [["2024-03-31", "W14 2024"], 11.0, 2],
        [["2024-12-29", "W1 2025"], 15.0, 2],
    ],
    month: [
        [["2024-01-01", "January 2024"], 10.0, 4],
        [["2024-03-01", "March 2024"], 5.0, 1],
        [["2024-04-01", "April 2024"], 6.0, 1],
        [["2024-12-01", "December 2024"], 7.0, 1],
        [["2025-01-01", "January 2025"], 8.0, 1],
    ],
    quarter: [
        [["2024-01-01", "Q1 2024"], 15.0, 5],
        [["2024-04-01", "Q2 2024"], 6.0, 1],
        [["2024-10-01", "Q4 2024"], 7.0, 1],
        [["2025-01-01", "Q1 2025"], 8.0, 1],
    ],
    year: [
        [["2024-01-01", "2024"], 28.0, 7],
        [["2025-01-01", "2025"], 8.0, 1],
    ],
    day_of_week: [
        [0.0, 8.0, 2],
        [1.0, 18.0, 4],
        [4.0, 8.0, 1],
        [5.0, 2.0, 1],
    ],
    iso_week_number: [
        [1.0, 21.0, 5],
        [2.0, 4.0, 1],
        [13.0, 5.0, 1],
        [14.0, 6.0, 1],
    ],
    month_number: [
        [1.0, 18.0, 5],
        [3.0, 5.0, 1],
        [4.0, 6.0, 1],
        [12.0, 7.0, 1],
    ],
    quarter_number: [
        [1.0, 23.0, 6],
        [2.0, 6.0, 1],
        [4.0, 7.0, 1],
    ],
    year_number: [
        [2024.0, 28.0, 7],
        [2025.0, 8.0, 1],
    ],
    day_of_month: [
        [1.0, 7.0, 2],
        [2.0, 8.0, 1],
        [5.0, 2.0, 1],
        [7.0, 3.0, 1],
        [8.0, 4.0, 1],
        [30.0, 7.0, 1],
        [31.0, 5.0, 1],
    ],
    day_of_year: [
        [1.0, 1.0, 1],
        [2.0, 8.0, 1],
        [5.0, 2.0, 1],
        [7.0, 3.0, 1],
        [8.0, 4.0, 1],
        [91.0, 5.0, 1],
        [92.0, 6.0, 1],
        [365.0, 7.0, 1],
    ],
};

/**
 * Granularities the mock does not reproduce.
 *
 * `day` — labelling only. The server formats the bucket with Babel's
 * `dd MMM yyyy` ("01 Jan 2024"); the mock emits the raw `yyyy-MM-dd`. Buckets
 * and aggregates agree, so only a suite asserting on a group HEADER sees it —
 * and every such suite is asserting a string production never renders.
 *
 * `week` — buckets, aggregates and counts, which is the severe kind. The server
 * offsets `date_trunc('week', …)` by the language's `week_start`
 * (`read_group/sql.py`); the mock reads Luxon's `WW kkkk`, which is ISO-8601 and
 * always starts Monday. `MockServer._lang_parameters` says `week_start: 7`, so
 * the mock carries the setting and ignores it: 2024-03-31 and 2024-04-01 are one
 * Sunday-start week summing 11.0 on the server, and two ISO weeks of 5.0 and 6.0
 * in the mock.
 *
 * The fix is not a format string. `src/core/l10n/date_utils.js` already has
 * `getLocalYearAndWeek()`, which the real client uses and which reproduces all
 * four server buckets here; the mock should call it instead of re-deriving weeks
 * from Luxon. What blocks a one-line change is that the surrounding code
 * recovers each bucket's start by RE-PARSING its own label
 * (`parseDateTime(value, { format: "WW kkkk" })`), so the label and the range
 * are coupled and a locale-aware label cannot be parsed back unambiguously.
 * Breaking that coupling — carrying the bucket start rather than re-deriving it
 * — is the actual change, and it belongs in its own commit.
 */
const KNOWN_DIVERGENCES = new Set(["day", "week"]);

/**
 * @param {string} granularity
 * @returns {[any, number, number][] | null}
 */
function mockVerdict(granularity) {
    try {
        const groups = MockServer.env["res.currency.rate"].formatted_read_group(
            [],
            [`name:${granularity}`],
            ["rate:sum", "__count"],
        );
        return groups.map((group) => [
            group[`name:${granularity}`],
            group["rate:sum"],
            group["__count"],
        ]);
    } catch {
        return null;
    }
}

test("formatted_read_group granularity agrees with the server", async () => {
    await makeMockServer();
    const disagreements = [];
    for (const [granularity, expected] of Object.entries(SERVER)) {
        if (KNOWN_DIVERGENCES.has(granularity)) {
            continue;
        }
        const got = mockVerdict(granularity);
        if (JSON.stringify(got) !== JSON.stringify(expected)) {
            disagreements.push(
                `${granularity}: server=${JSON.stringify(expected)} ` +
                    `mock=${JSON.stringify(got)}`,
            );
        }
    }
    expect(disagreements).toEqual([]);
});

test("the mock/server read_group gap has not grown or silently closed", async () => {
    await makeMockServer();
    const nowDivergent = new Set();
    for (const [granularity, expected] of Object.entries(SERVER)) {
        if (JSON.stringify(mockVerdict(granularity)) !== JSON.stringify(expected)) {
            nowDivergent.add(granularity);
        }
    }
    expect([...nowDivergent].filter((g) => !KNOWN_DIVERGENCES.has(g))).toEqual([]);
    expect([...KNOWN_DIVERGENCES].filter((g) => !nowDivergent.has(g))).toEqual([]);
});
