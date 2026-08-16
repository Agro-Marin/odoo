import { computeDelay, getMsToTomorrow, isToday } from "@mail/utils/common/dates";
import { beforeEach, describe, expect, mockDate, test } from "@odoo/hoot";
import { freezeTime } from "@odoo/hoot-dom";
import { DateTime, FixedOffsetZone, Settings } from "@web/core/l10n/luxon";

const userZone = (hours) => FixedOffsetZone.instance(hours * 60);

describe.current.tags("headless");

beforeEach(freezeTime);

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
    mockDate("2026-03-10T16:00:00", 0);
    withUserZone(userZone(9), () => {
        const landing = DateTime.now().plus({ milliseconds: getMsToTomorrow() });
        expect(landing.hour).toBe(0, { message: "the timer fires at a midnight" });
        expect(+landing).toBe(+DateTime.now().startOf("day").plus({ days: 1 }), {
            message: "...and specifically the user's next midnight",
        });
        const deadline = DateTime.now().startOf("day");
        expect(computeDelay(deadline)).toBe(0);
    });
});

test("the browser's midnight is genuinely a different instant here", () => {
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
        const userToday = DateTime.now().startOf("day");
        expect(isToday(userToday)).toBe(true);
        expect(computeDelay(userToday)).toBe(0);
        expect(isToday(userToday.minus({ days: 1 }))).toBe(false);
    });
});
