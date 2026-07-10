// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { isInRange } from "@web/core/l10n/date_utils";
import { luxon } from "@web/core/l10n/luxon";

const { DateTime } = luxon;

describe.current.tags("headless");

describe("isInRange", () => {
    test("single DateTime value", () => {
        const range = [
            DateTime.fromISO("2024-01-01T10:20:00Z"),
            DateTime.fromISO("2024-01-01T10:40:00Z"),
        ];
        expect(isInRange(DateTime.fromISO("2024-01-01T10:30:00Z"), range)).toBe(true);
        expect(isInRange(DateTime.fromISO("2024-01-01T12:00:00Z"), range)).toBe(false);
    });

    test("falsy value or range", () => {
        const range = [
            DateTime.fromISO("2024-01-01T10:20:00Z"),
            DateTime.fromISO("2024-01-01T10:40:00Z"),
        ];
        expect(isInRange(null, range)).toBe(false);
        expect(isInRange(DateTime.now(), null)).toBe(false);
    });

    test("array with a single truthy value falls back to single-value check", () => {
        const range = [
            DateTime.fromISO("2024-01-01T10:20:00Z"),
            DateTime.fromISO("2024-01-01T10:40:00Z"),
        ];
        expect(isInRange([DateTime.fromISO("2024-01-01T10:30:00Z"), null], range)).toBe(
            true,
        );
        expect(isInRange([null, DateTime.fromISO("2024-01-01T12:00:00Z")], range)).toBe(
            false,
        );
    });

    test("sorts a mixed-offset array chronologically, not by ISO string", () => {
        // `earlier` is the earlier instant but has the *larger* ISO string
        // ("…T10:00…Z"); `later` is the later instant rendered in a negative
        // offset so its ISO string ("…T01:00…-10:00") sorts first. A plain
        // `.sort()` (by string) would order them backwards and misjudge the
        // range; a numeric sort keys on the true instant.
        const earlier = DateTime.fromISO("2024-01-01T10:00:00", { zone: "UTC" });
        const later = DateTime.fromISO("2024-01-01T11:00:00", { zone: "UTC" }).setZone(
            "UTC-10",
        );
        const insideRange = [
            DateTime.fromISO("2024-01-01T10:20:00Z"),
            DateTime.fromISO("2024-01-01T10:40:00Z"),
        ];
        const outsideRange = [
            DateTime.fromISO("2024-01-01T12:00:00Z"),
            DateTime.fromISO("2024-01-01T13:00:00Z"),
        ];
        // The value interval is [10:00Z, 11:00Z]; the range sits fully inside.
        expect(isInRange([later, earlier], insideRange)).toBe(true);
        expect(isInRange([earlier, later], insideRange)).toBe(true);
        expect(isInRange([later, earlier], outsideRange)).toBe(false);
    });
});
