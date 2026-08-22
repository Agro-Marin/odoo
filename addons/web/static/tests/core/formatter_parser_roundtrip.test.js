// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { makeMockEnv, patchWithCleanup } from "@web/../tests/web_test_helpers";
import {
    formatFieldDate,
    formatFieldDateTime,
    formatFieldFloat,
    formatFloatTime,
    formatInteger,
    formatMonetary,
    formatPercentage,
} from "@web/core/formatters";
import { parseDate, parseDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { DateTime } from "@web/core/l10n/luxon";
import {
    parseFloat,
    parseFloatTime,
    parseInteger,
    parseMonetary,
    parsePercentage,
} from "@web/core/parsers";
import { nbsp } from "@web/core/utils/format/strings";

describe.current.tags("headless");

beforeEach(makeMockEnv);

/**
 * @type {{ name: string, format: (v: any, o?: any) => string, parse: (s: string) => number, domain?: (v: number) => number }[]}
 */
const PAIRS = [
    { name: "float", format: formatFieldFloat, parse: parseFloat },
    { name: "integer", format: formatInteger, parse: parseInteger, domain: Math.round },
    { name: "float_time", format: formatFloatTime, parse: parseFloatTime },
    {
        name: "percentage",
        format: formatPercentage,
        parse: /** @type {(s: string) => number} */ (parsePercentage),
    },
    { name: "monetary", format: formatMonetary, parse: parseMonetary },
];

/**
 * @type {{
 * name: string,
 * decimalPoint: string,
 * thousandsSep: string | false,
 * grouping: number[],
 * }[]}
 */
const LOCALES = [
    { name: "en_US", decimalPoint: ".", thousandsSep: ",", grouping: [3, 0] },
    { name: "fr_BE", decimalPoint: ",", thousandsSep: ".", grouping: [3, 0] },
    { name: "fr_FR nbsp", decimalPoint: ",", thousandsSep: nbsp, grouping: [3, 0] },
    {
        name: "no thousands sep",
        decimalPoint: ",",
        thousandsSep: false,
        grouping: [3, 0],
    },
    { name: "hi_IN", decimalPoint: ".", thousandsSep: ",", grouping: [3, 2, 0] },
];

const VALUES = [
    0, 1, -1, 0.5, -0.5, 2.25, -2.25, 12.34, -12.34, 100, 999, 1000, -1000, 1234.56,
    -1234.56, 999999.99, 1000000, 12345678.9, -12345678.9, 0.01, -0.01, 1e9, 123456789,
];

test("formatInteger never renders a negative zero", () => {
    expect(formatInteger(-0.01)).toBe("0");
    expect(formatInteger(-0.4)).toBe("0");
    expect(formatInteger(-0)).toBe("0");
    expect(formatInteger(0)).toBe("0");
    expect(formatInteger(-1)).toBe("-1");
    expect(formatInteger(-1.9)).toBe("-2");
});

describe("dates round trip through the numeric rendering", () => {
    const FORMATS = [
        { dateFormat: "MM/dd/yyyy", dateTimeFormat: "MM/dd/yyyy HH:mm:ss" },
        { dateFormat: "dd/MM/yyyy", dateTimeFormat: "dd/MM/yyyy HH:mm:ss" },
        { dateFormat: "yyyy-MM-dd", dateTimeFormat: "yyyy-MM-dd HH:mm:ss" },
        { dateFormat: "d/M/yy", dateTimeFormat: "d/M/yy HH:mm:ss" },
    ];
    const DAYS = [
        [2024, 1, 1],
        [2024, 2, 29],
        [2024, 12, 31],
        [1999, 6, 15],
        [2001, 11, 7],
    ];

    for (const fmt of FORMATS) {
        test(`date in ${fmt.dateFormat}`, () => {
            patchWithCleanup(localization, fmt);
            const drifted = [];
            for (const [y, m, d] of DAYS) {
                const value = DateTime.local(y, m, d);
                const shown = formatFieldDate(value, { numeric: true });
                const back = parseDate(shown);
                const got = back && back.toFormat("yyyy-MM-dd");
                if (got !== value.toFormat("yyyy-MM-dd")) {
                    drifted.push(
                        `${value.toFormat("yyyy-MM-dd")} -> ${shown} -> ${got}`,
                    );
                }
            }
            expect(drifted).toEqual([]);
        });

        test(`datetime in ${fmt.dateTimeFormat}`, () => {
            patchWithCleanup(localization, fmt);
            const drifted = [];
            for (const [y, m, d] of DAYS) {
                const value = DateTime.local(y, m, d, 13, 45, 7);
                const shown = formatFieldDateTime(value, { numeric: true });
                const back = parseDateTime(shown);
                const got = back && back.toFormat("yyyy-MM-dd HH:mm:ss");
                const want = value.toFormat("yyyy-MM-dd HH:mm:ss");
                if (got !== want) {
                    drifted.push(`${want} -> ${shown} -> ${got}`);
                }
            }
            expect(drifted).toEqual([]);
        });
    }
});

for (const locale of LOCALES) {
    describe(`round trip in ${locale.name}`, () => {
        for (const pair of PAIRS) {
            test(`${pair.name} is stable under a second trip`, () => {
                patchWithCleanup(localization, {
                    decimalPoint: locale.decimalPoint,
                    thousandsSep: locale.thousandsSep,
                    grouping: locale.grouping,
                });
                /** @type {string[]} */
                const drifted = [];
                for (const raw of VALUES) {
                    const value = pair.domain ? pair.domain(raw) : raw;
                    const once = pair.format(value);
                    let twice;
                    try {
                        twice = pair.format(pair.parse(once));
                    } catch (error) {
                        drifted.push(
                            `${value} -> ${JSON.stringify(once)} -> threw ${error}`,
                        );
                        continue;
                    }
                    if (twice !== once) {
                        drifted.push(
                            `${value} -> ${JSON.stringify(once)} -> ${JSON.stringify(twice)}`,
                        );
                    }
                }
                expect(drifted).toEqual([]);
            });
        }
    });
}
