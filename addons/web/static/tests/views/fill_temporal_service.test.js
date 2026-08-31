// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { mockDate } from "@odoo/hoot-mock";
import { FillTemporal, GRANULARITY_TABLE } from "@web/views/fill_temporal_service";

describe.current.tags("headless");

const DATE_FIELD = { name: "date_deadline", type: "date" };
const FIELDS = { date_deadline: DATE_FIELD };

function service() {
    return new FillTemporal();
}

function forGroupBy(svc, groupBySpec, extra = {}) {
    return svc.getFillTemporalPeriodForGroupBy({
        modelName: "crm.lead",
        groupBySpec,
        fields: FIELDS,
        ...extra,
    });
}

describe("cache key derivation", () => {
    test("a groupBy spec's granularity decides the slot", () => {
        mockDate("2021-10-10 12:00:00");
        const svc = service();
        const year = forGroupBy(svc, "date_deadline:year");
        const month = forGroupBy(svc, "date_deadline:month");
        expect(year).not.toBe(month);
        expect([year.granularity, month.granularity]).toEqual(["year", "month"]);
    });

    test("a bare spec defaults to month, and hits the same slot as an explicit one", () => {
        mockDate("2021-10-10 12:00:00");
        const svc = service();
        expect(forGroupBy(svc, "date_deadline")).toBe(
            forGroupBy(svc, "date_deadline:month"),
        );
    });

    test("expanding through the shared derivation reaches the slot it names", () => {
        // the defect this suite exists for: a caller that read `granularity` off
        // the field descriptor always got "month" and expanded an unread period.
        mockDate("2021-10-10 12:00:00");
        const svc = service();
        const before = forGroupBy(svc, "date_deadline:year").end;
        forGroupBy(svc, "date_deadline:year").expand();
        const after = forGroupBy(svc, "date_deadline:year").end;
        expect(after.diff(before, "years").years).toBe(1);
        expect(forGroupBy(svc, "date_deadline:month").end.equals(after)).toBe(false);
    });
});

describe("minGroups", () => {
    test("sizes the derived end on a fresh period", () => {
        mockDate("2021-10-10 12:00:00");
        const months = (n) =>
            Math.round(
                forGroupBy(service(), "date_deadline:month", { minGroups: n }).end.diff(
                    forGroupBy(service(), "date_deadline:month", { minGroups: n })
                        .start,
                    "months",
                ).months,
            );
        expect(months(4)).toBe(15);
        expect(months(16)).toBe(27);
    });

    test("a caller that omits it leaves a configured minimum alone", () => {
        mockDate("2021-10-10 12:00:00");
        const svc = service();
        forGroupBy(svc, "date_deadline:month", { minGroups: 12 });
        expect(forGroupBy(svc, "date_deadline:month").minGroups).toBe(12);
    });

    test("a caller that supplies it resizes the still-derived end", () => {
        mockDate("2021-10-10 12:00:00");
        const svc = service();
        const p = forGroupBy(svc, "date_deadline:month", { minGroups: 4 });
        const end4 = p.end;
        forGroupBy(svc, "date_deadline:month", { minGroups: 16 });
        expect(p.minGroups).toBe(16);
        expect(p.end.equals(end4)).toBe(false);
        expect(p.getContext({}).fill_temporal.min_groups).toBe(16);
    });

    test("but never a deliberately set end", () => {
        mockDate("2021-10-10 12:00:00");
        const svc = service();
        const p = forGroupBy(svc, "date_deadline:month", { minGroups: 4 });
        p.setEnd(p.start.plus({ months: 2 }));
        const deliberate = p.end;
        forGroupBy(svc, "date_deadline:month", { minGroups: 16 });
        expect(p.end.equals(deliberate)).toBe(true);
    });
});

describe("re-anchoring", () => {
    test("a cached period follows the clock across a period boundary", () => {
        mockDate("2021-10-15 12:00:00");
        const svc = service();
        expect(
            forGroupBy(svc, "date_deadline:month").getContext({}).fill_temporal
                .fill_from,
        ).toBe("2021-10-01");

        mockDate("2021-12-20 12:00:00");
        expect(
            forGroupBy(svc, "date_deadline:month").getContext({}).fill_temporal
                .fill_from,
        ).toBe("2021-12-01");
    });

    test("re-anchoring keeps a deliberate end, clamped to the new start", () => {
        mockDate("2021-10-15 12:00:00");
        const svc = service();
        const p = forGroupBy(svc, "date_deadline:month");
        p.setEnd(p.start.plus({ months: 1 })); // 2021-11-01, now in the past
        mockDate("2021-12-20 12:00:00");
        forGroupBy(svc, "date_deadline:month");
        expect(p.start.toISODate()).toBe("2021-12-01");
        expect(p.end >= p.start).toBe(true);
    });

    test("forceRecompute replaces the instance", () => {
        mockDate("2021-10-15 12:00:00");
        const svc = service();
        const first = forGroupBy(svc, "date_deadline:month");
        expect(
            forGroupBy(svc, "date_deadline:month", { forceRecompute: true }),
        ).not.toBe(first);
    });
});

describe("cycle arithmetic", () => {
    test("every granularity in the table produces a period ahead of its start", () => {
        mockDate("2021-10-15 12:00:00");
        for (const granularity of Object.keys(GRANULARITY_TABLE)) {
            const p = forGroupBy(service(), `date_deadline:${granularity}`, {
                minGroups: 4,
            });
            expect(p.end > p.start).toBe(true, {
                message: `${granularity}: end must be after start`,
            });
        }
    });

    test("expand adds exactly one granularity step", () => {
        mockDate("2021-10-15 12:00:00");
        for (const granularity of Object.keys(GRANULARITY_TABLE)) {
            const p = forGroupBy(service(), `date_deadline:${granularity}`);
            const before = p.end;
            p.expand();
            expect(p.end.diff(before, granularity)[`${granularity}s`]).toBe(1, {
                message: `${granularity}: expand() adds one step`,
            });
        }
    });
});

describe("domain and context", () => {
    test("both bounds, ORed with the falsy leaf", () => {
        mockDate("2021-10-15 12:00:00");
        const p = forGroupBy(service(), "date_deadline:month", { minGroups: 4 });
        expect(p.getDomain({ domain: [["a", "=", 1]] })).toEqual([
            "&",
            ["a", "=", 1],
            "|",
            ["date_deadline", "=", false],
            "&",
            ["date_deadline", ">=", "2021-10-01"],
            ["date_deadline", "<", "2023-01-01"],
        ]);
    });

    test("neither bound returns the domain untouched", () => {
        mockDate("2021-10-15 12:00:00");
        const p = forGroupBy(service(), "date_deadline:month");
        const domain = [["a", "=", 1]];
        expect(
            p.getDomain({ domain, forceStartBound: false, forceEndBound: false }),
        ).toBe(domain);
    });

    test("a single bound drops the linking operator", () => {
        mockDate("2021-10-15 12:00:00");
        const p = forGroupBy(service(), "date_deadline:month");
        expect(p.getDomain({ domain: [], forceStartBound: false })).toEqual([
            "|",
            ["date_deadline", "=", false],
            ["date_deadline", "<", "2023-01-01"],
        ]);
    });

    test("a derived end sends no fill_to; a deliberate one does", () => {
        mockDate("2021-10-15 12:00:00");
        const p = forGroupBy(service(), "date_deadline:month");
        expect(p.getContext({}).fill_temporal.fill_to).toBe(undefined);
        p.setEnd(p.start.plus({ months: 3 }));
        expect(p.getContext({}).fill_temporal.fill_to).toBe("2021-12-31");
    });

    test("a date is sent unshifted; a datetime is converted to UTC", () => {
        // the class comments this asymmetry: the server wants UTC, but a date
        // must not shift a day on the way there.
        mockDate("2021-10-15 12:00:00");
        const dateFrom = forGroupBy(service(), "date_deadline:month").getContext({})
            .fill_temporal.fill_from;
        const datetimeFrom = service()
            .getFillTemporalPeriodForGroupBy({
                modelName: "crm.lead",
                groupBySpec: "create_date:month",
                fields: { create_date: { name: "create_date", type: "datetime" } },
            })
            .getContext({}).fill_temporal.fill_from;
        expect(dateFrom).toBe("2021-10-01");
        expect(datetimeFrom).toMatch(/^2021-(09-30|10-01) \d{2}:\d{2}:\d{2}$/);
        expect(datetimeFrom.slice(0, 10)).not.toBe("2021-10-15");
    });
});
