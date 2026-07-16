// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { defineParams, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { localization } from "@web/core/l10n/localization";
import { luxon } from "@web/core/l10n/luxon";
import { parseTime } from "@web/core/l10n/time";

const { Settings } = luxon;

defineParams({
    lang_parameters: {
        time_format: "%H:%M:%S",
    },
});

beforeEach(() => {
    patchWithCleanup(localization, {
        timeFormat: "%H:%M:%S",
    });
});

describe.current.tags("headless");
test("parseTime (various entries)", async () => {
    const testSet = [
        // Default ":" separator
        ["8:15", "8:15:00"],
        ["15:15", "15:15:00"],
        ["15:5", "15:50:00"],
        ["15:15:34", "15:15:34"],
        ["24:00", "0:00:00"],
        ["10:", "10:00:00"],

        // No separators
        ["123", "12:30:00"],
        ["101", "10:10:00"],
        ["1015", "10:15:00"],
        ["101534", "10:15:34"],
        ["10  15", "10:15:00"],
        ["10  15   34", "10:15:34"],
        ["1 15", "1:15:00"],
        ["35", "3:50:00"],

        // Am / Pm
        ["8pm", "20:00:00"],
        ["8PM", "20:00:00"],
        ["8 pm", "20:00:00"],
        ["8:55pm", "20:55:00"],
        ["8:55 pm", "20:55:00"],
        ["8:55pm 33", "20:55:33"],
        ["8:55:33pm", "20:55:33"],
        ["8h pm", "20:00:00"],

        ["12am", "0:00:00"],
        ["12pm", "12:00:00"],

        // Ignore any non-numeric characters
        ["10h", "10:00:00"],
        ["1abc30", "1:30:00"],
        ["10abc15", "10:15:00"],
        ["10abc15:34", "10:15:34"],
        ["10abc35abc25abc", "10:35:25"],
        ["10abc 35", "10:35:00"],
        ["10 35abc", "10:35:00"],
        ["abc8", "8:00:00"],

        // Wrong inputs
        ["28:00", null],
        // "24" is only valid as ISO 8601 end-of-day ("24:00"): accepting
        // "24:30" would silently produce "0:30".
        ["24:30", null],
        ["24:00:01", null],
        ["2430", null],
        ["10101010", null],
        ["abc", null],
        ["", null],
        [" ", null],
        [null, null],
        [undefined, null],
        [false, null],
        [true, null],
    ];

    for (const [input, expected] of testSet) {
        let result = parseTime(input, true);
        if (result) {
            result = result.toString(true);
        }
        expect(result).toBe(expected, {
            message: `"${input}" should parse to "${expected}" and got "${result}"`,
        });
    }
});

describe.current.tags("headless");
test("parseTime (3-digit '24x' resolves to 2:4x, not end-of-day)", async () => {
    // Regression: the "[24, x]" split passed the ``h <= 24`` gate before its
    // minutes were validated, so "240" was consumed as hour 24 (→ 0:00) and
    // "241".."249" were rejected outright. The intended "[2, 4x]" reading must
    // win instead. Bare "24" (no minutes) stays ISO end-of-day (→ 0:00).
    const testSet = [
        ["240", "2:40:00"],
        ["241", "2:41:00"],
        ["245", "2:45:00"],
        ["249", "2:49:00"],
        ["250", "2:50:00"],
        // Unchanged neighbours / end-of-day semantics
        ["24", "0:00:00"],
        ["230", "23:00:00"],
        ["210", "21:00:00"],
        ["350", "3:50:00"],
        ["2430", null],
    ];

    for (const [input, expected] of testSet) {
        let result = parseTime(input, true);
        if (result) {
            result = result.toString(true);
        }
        expect(result).toBe(expected, {
            message: `"${input}" should parse to "${expected}" and got "${result}"`,
        });
    }
});

describe.current.tags("headless");
test("parseTime (no seconds)", async () => {
    const testSet = [
        ["8:15", "8:15"],
        ["10:15", "10:15"],
        ["10:5", "10:50"],
        ["24:00", "0:00"],
        ["10:", "10:00"],
        ["101", "10:10"],
        ["350", "3:50"],
        ["1015", "10:15"],
        ["10  15", "10:15"],
        ["1 15", "1:15"],
        ["8:55abc", "8:55"],
        ["8:55:", "8:55"],

        ["24:30", null],
        ["8:55:33", null],
        ["08553", null],
        ["085533", null],
        ["08553300", null],
        ["8:55:33pm", null],
    ];

    for (const [input, expected] of testSet) {
        let result = parseTime(input, false);
        if (result) {
            result = result.toString(false);
        }
        expect(result).toBe(expected, {
            message: `(parseSeconds=false) "${input}" should parse to "${expected}" and got "${result}"`,
        });
    }
});

describe.current.tags("headless");
test("parseTime (arabic numbers)", async () => {
    patchWithCleanup(Settings, { defaultNumberingSystem: "arab" });

    const testSet = [
        ["11", "١١:٠٠"],
        ["11:45", "١١:٤٥"],
        ["١١", "١١:٠٠"],
        ["١١:٤٥", "١١:٤٥"],
    ];

    for (const [input, expected] of testSet) {
        const result = parseTime(input).toString(false);
        expect(result).toBe(expected, {
            message: `"${input}" should parse to "${expected}" and got "${result}"`,
        });
    }
});
