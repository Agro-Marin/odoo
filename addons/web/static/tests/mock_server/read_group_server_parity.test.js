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

class CurrencyRate extends models.Model {
    _name = "res.currency.rate";

    name = fields.Date();
    rate = fields.Float();

    _records = [
        { id: 1, name: "2024-01-01", rate: 1.0 },
        { id: 2, name: "2024-01-05", rate: 2.0 },
        { id: 3, name: "2024-01-07", rate: 3.0 },
        { id: 4, name: "2024-01-08", rate: 4.0 },
        { id: 5, name: "2024-03-31", rate: 5.0 },
        { id: 6, name: "2024-04-01", rate: 6.0 },
        { id: 7, name: "2024-12-30", rate: 7.0 },
        { id: 8, name: "2025-01-02", rate: 8.0 },
    ];
}

defineModels([CurrencyRate]);

/**
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
        return groups.map((/** @type {Record<string, any>} */ group) => [
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
