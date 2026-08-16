import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { computeUpdateDelay } from "@mail/core/common/relative_time";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");
defineMailModels();

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;

test("a just-posted message sleeps until the label can change", () => {
    expect(computeUpdateDelay(5)).toBe(45 * SECOND - 5);
    expect(computeUpdateDelay(SECOND)).toBe(44 * SECOND);
    expect(computeUpdateDelay(44 * SECOND)).toBe(SECOND);
    expect(computeUpdateDelay(0)).toBe(45 * SECOND);
});

test("a future datetime never overshoots the moment it becomes present", () => {
    expect(computeUpdateDelay(-59_939)).toBe(59_939);
    expect(computeUpdateDelay(-30 * SECOND)).toBe(30 * SECOND);
    expect(computeUpdateDelay(-SECOND)).toBe(SECOND);
    expect(computeUpdateDelay(-2 * MINUTE)).toBe(MINUTE);
    expect(computeUpdateDelay(-59 * MINUTE)).toBe(MINUTE);
    expect(computeUpdateDelay(-3 * HOUR)).toBe(HOUR);
});

test("past datetimes keep the minute / hour cadence", () => {
    expect(computeUpdateDelay(46 * SECOND)).toBe(MINUTE);
    expect(computeUpdateDelay(30 * MINUTE)).toBe(MINUTE);
    expect(computeUpdateDelay(HOUR)).toBe(HOUR);
    expect(computeUpdateDelay(5 * HOUR)).toBe(HOUR);
});

test("the delay is always positive, so a render can never loop", () => {
    for (const delta of [0, -1, 1, -HOUR, HOUR, -24 * HOUR, 24 * HOUR]) {
        expect(computeUpdateDelay(delta)).toBeGreaterThan(0);
    }
});
