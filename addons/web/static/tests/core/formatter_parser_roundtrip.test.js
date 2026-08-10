// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { makeMockEnv, patchWithCleanup } from "@web/../tests/web_test_helpers";
import {
    formatDate,
    formatDateTime,
    formatFloat,
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
 * A formatter and its parser are an editing contract, not two independent
 * functions: the user is shown `format(value)`, may edit it, and whatever comes
 * back is `parse`d. So opening a field and saving it untouched must not move
 * the value, in ANY locale -- and until this file there was no round-trip test
 * of the pair at all.
 *
 * The property is stated on the *rendering* rather than on the number:
 * `format` rounds to the field's digits, so `parse(format(x))` cannot equal an
 * `x` carrying more precision. What must hold is that a second trip changes
 * nothing.
 *
 *     format(parse(format(x))) === format(x)
 *
 * `integer` is swept over the values rounded rather than the values themselves:
 * `parseInteger` rejects a fractional string outright, so a fractional input is
 * outside the pair's domain and would test nothing about the contract.
 *
 * @type {{ name: string, format: (v: any, o?: any) => string, parse: (s: string) => number, domain?: (v: number) => number }[]}
 */
const PAIRS = [
    { name: "float", format: formatFloat, parse: parseFloat },
    { name: "integer", format: formatInteger, parse: parseInteger, domain: Math.round },
    { name: "float_time", format: formatFloatTime, parse: parseFloatTime },
    { name: "percentage", format: formatPercentage, parse: parsePercentage },
    { name: "monetary", format: formatMonetary, parse: parseMonetary },
];

/** Locales that differ in every axis the number code branches on. */
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
    // Indian grouping is the case a fixed 3-digit assumption gets wrong.
    { name: "hi_IN", decimalPoint: ".", thousandsSep: ",", grouping: [3, 2, 0] },
];

const VALUES = [
    0, 1, -1, 0.5, -0.5, 2.25, -2.25, 12.34, -12.34, 100, 999, 1000, -1000, 1234.56,
    -1234.56, 999999.99, 1000000, 12345678.9, -12345678.9, 0.01, -0.01, 1e9, 123456789,
];

// Found by the sweep above, which reported `-0.01 -> "-0" -> "0"` in every
// locale: `toFixed(0)` keeps the sign of anything in (-1, 0). There is no
// negative zero integer on the server, so the rendering was never reachable
// from a stored value -- but any caller handing formatInteger a fraction got a
// string that reads as a bug.
test("formatInteger never renders a negative zero", () => {
    expect(formatInteger(-0.01)).toBe("0");
    expect(formatInteger(-0.4)).toBe("0");
    expect(formatInteger(-0)).toBe("0");
    expect(formatInteger(0)).toBe("0");
    // and the sign survives where it means something
    expect(formatInteger(-1)).toBe("-1");
    expect(formatInteger(-1.9)).toBe("-2");
});

/**
 * Dates round-trip through the NUMERIC rendering, which is the one the widget
 * actually feeds back: `datetime_field` renders the locale form ("Nov 7, 2001")
 * as the button's text but carries `value="11/07/2001"` for editing, and
 * `parseDate` reads `localization.dateFormat`. The locale form is display-only
 * and is deliberately not asserted here -- it does not round-trip, and it is
 * not meant to.
 */
describe("dates round trip through the numeric rendering", () => {
    const FORMATS = [
        { dateFormat: "MM/dd/yyyy", dateTimeFormat: "MM/dd/yyyy HH:mm:ss" },
        { dateFormat: "dd/MM/yyyy", dateTimeFormat: "dd/MM/yyyy HH:mm:ss" },
        { dateFormat: "yyyy-MM-dd", dateTimeFormat: "yyyy-MM-dd HH:mm:ss" },
        { dateFormat: "d/M/yy", dateTimeFormat: "d/M/yy HH:mm:ss" },
    ];
    const DAYS = [
        [2024, 1, 1],
        [2024, 2, 29], // leap day
        [2024, 12, 31], // year end
        [1999, 6, 15],
        [2001, 11, 7], // single-digit day and month, two-digit year format
    ];

    for (const fmt of FORMATS) {
        test(`date in ${fmt.dateFormat}`, () => {
            patchWithCleanup(localization, fmt);
            const drifted = [];
            for (const [y, m, d] of DAYS) {
                const value = DateTime.local(y, m, d);
                const shown = formatDate(value, { numeric: true });
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
                const shown = formatDateTime(value, { numeric: true });
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
