import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { computeUpdateDelay } from "@mail/core/common/relative_time";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");
defineMailModels();

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;

/**
 * The label changes at three kinds of boundary: a past datetime leaving the 45s
 * "now" window, a future one becoming present, and the minute / hour ticks of
 * the relative text in between. Waking up at any other time re-renders the same
 * string; waking up later than one of them shows a stale string.
 */
test("a just-posted message sleeps until the label can change", () => {
    // 5ms old: the next possible change is the 45s boundary. Scheduling on the
    // raw distance re-rendered at 5ms, 10ms, 20ms, ... to produce "now" again.
    expect(computeUpdateDelay(5)).toBe(45 * SECOND - 5);
    expect(computeUpdateDelay(SECOND)).toBe(44 * SECOND);
    expect(computeUpdateDelay(44 * SECOND)).toBe(SECOND);
    // exactly "now": the label holds for the whole window
    expect(computeUpdateDelay(0)).toBe(45 * SECOND);
});

test("a future datetime never overshoots the moment it becomes present", () => {
    // within a cadence tick of the crossing, wake at the crossing — rounding up
    // to a full minute leaves "in a few seconds" on screen after the fact
    expect(computeUpdateDelay(-59_939)).toBe(59_939);
    expect(computeUpdateDelay(-30 * SECOND)).toBe(30 * SECOND);
    expect(computeUpdateDelay(-SECOND)).toBe(SECOND);
    // further out, the countdown text ticks on the coarse cadence
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
