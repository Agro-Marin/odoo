import { computeDelay, getMsToTomorrow, isToday } from "@mail/utils/common/dates";
import { describe, expect, mockDate, test } from "@odoo/hoot";
import { DateTime, FixedOffsetZone, Settings } from "@web/core/l10n/luxon";

/** Odoo user timezone as a fixed offset, in hours. */
const userZone = (hours) => FixedOffsetZone.instance(hours * 60);

describe.current.tags("headless");

/**
 * Run `fn` with luxon's default zone forced to `zone`, i.e. with the Odoo user
 * timezone differing from the browser's. `@web/boot/start` sets
 * `Settings.defaultZone = user.tz`, so this is the ordinary state for anyone
 * whose Odoo timezone is not their OS timezone (travel, VPN, a profile pinned
 * to head office).
 */
function withUserZone(zone, fn) {
    const previous = Settings.defaultZone;
    Settings.defaultZone = zone;
    try {
        return fn();
    } finally {
        Settings.defaultZone = previous;
    }
}

test("getMsToTomorrow lands on midnight in the user's timezone", () => {
    // Browser is UTC+0, the Odoo user is UTC+9, and it is 16:00 UTC -- so it is
    // already 01:00 *tomorrow* for the user. Their next midnight is therefore
    // 23h away, while the browser's own is 8h away: the two answers are far
    // apart, and only one of them is the one the label depends on.
    mockDate("2026-03-10T16:00:00", 0);
    withUserZone(userZone(9), () => {
        const ms = getMsToTomorrow();
        const landing = DateTime.now().plus({ milliseconds: ms });
        expect(landing.toISO()).toBe(
            DateTime.now().plus({ days: 1 }).startOf("day").toISO(),
            {
                message:
                    "the timer must fire at the user's midnight, not the browser's",
            },
        );
        expect(Math.round(ms / 3600000)).toBe(23);
    });
});

test("getMsToTomorrow lands where computeDelay changes its answer", () => {
    // The contract Activity's midnight timer relies on: when it fires, the day
    // computeDelay grades deadlines against must have just advanced by one.
    mockDate("2026-03-10T16:00:00", 0);
    withUserZone(userZone(9), () => {
        const landing = DateTime.now().plus({ milliseconds: getMsToTomorrow() });
        expect(landing.hour).toBe(0, { message: "the timer fires at a midnight" });
        expect(+landing).toBe(+DateTime.now().startOf("day").plus({ days: 1 }), {
            message: "...and specifically the user's next midnight",
        });
        // A deadline of the user's today reads as today right up to the firing.
        const deadline = DateTime.now().startOf("day");
        expect(computeDelay(deadline)).toBe(0);
    });
});

test("the browser's midnight is genuinely a different instant here", () => {
    // Guards the two tests above from passing vacuously: if the mocked browser
    // zone ever coincided with the user zone, they would prove nothing.
    mockDate("2026-03-10T16:00:00", 0);
    const browserMidnight = new Date(2026, 2, 11, 0, 0, 0).getTime();
    withUserZone(userZone(9), () => {
        const userMidnight = +DateTime.now().startOf("day").plus({ days: 1 });
        expect(userMidnight).not.toBe(browserMidnight);
    });
});

test("getMsToTomorrow is positive and under 24h in every zone", () => {
    mockDate("2026-03-10T16:00:00", 0);
    for (const zone of [userZone(0), userZone(9), userZone(-5), userZone(14)]) {
        withUserZone(zone, () => {
            const ms = getMsToTomorrow();
            expect(ms > 0 && ms <= 24 * 3600 * 1000).toBe(true, {
                message: `offset ${zone.offset()}: expected a positive sub-24h delay, got ${ms}`,
            });
        });
    }
});

test("isToday and computeDelay share the user's timezone", () => {
    mockDate("2026-03-10T16:00:00", 0);
    withUserZone(userZone(9), () => {
        // 16:00 UTC == 01:00 on the 11th for the user.
        const userToday = DateTime.now().startOf("day");
        expect(isToday(userToday)).toBe(true);
        expect(computeDelay(userToday)).toBe(0);
        expect(isToday(userToday.minus({ days: 1 }))).toBe(false);
    });
});
