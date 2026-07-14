import {
    applyCounterAbsolute,
    applyCounterDelta,
    snapshotCounter,
} from "@mail/utils/common/counters";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");

function makeTarget(counter = 0, busId = 0) {
    return { counter, counter_bus_id: busId };
}

test("applyCounterAbsolute applies a newer snapshot and advances the bus id", () => {
    const target = makeTarget(3, 10);
    expect(applyCounterAbsolute(target, "counter", 7, 11)).toBe(true);
    expect(target.counter).toBe(7);
    expect(target.counter_bus_id).toBe(11);
});

test("applyCounterAbsolute ignores a stale or equal bus id", () => {
    const target = makeTarget(3, 10);
    expect(applyCounterAbsolute(target, "counter", 99, 10)).toBe(false);
    expect(applyCounterAbsolute(target, "counter", 99, 9)).toBe(false);
    expect(target.counter).toBe(3);
    expect(target.counter_bus_id).toBe(10);
});

test("applyCounterDelta clamps at the floor and returns the applied delta", () => {
    const target = makeTarget(1);
    expect(applyCounterDelta(target, "counter", -3)).toBe(-1);
    expect(target.counter).toBe(0);
    expect(applyCounterDelta(target, "counter", -1)).toBe(0);
    expect(target.counter).toBe(0);
    expect(applyCounterDelta(target, "counter", 2)).toBe(2);
    expect(target.counter).toBe(2);
    expect(applyCounterDelta(target, "counter", -5, { floor: 1 })).toBe(-1);
    expect(target.counter).toBe(1);
});

test("applyCounterDelta with a bus id is fenced and never advances the bus id", () => {
    const target = makeTarget(3, 10);
    // event already accounted for by the last absolute snapshot
    expect(applyCounterDelta(target, "counter", 1, { busId: 10 })).toBe(0);
    expect(applyCounterDelta(target, "counter", 1, { busId: 9 })).toBe(0);
    expect(target.counter).toBe(3);
    // newer event applies, but a delta is not a snapshot: bus id untouched
    expect(applyCounterDelta(target, "counter", 1, { busId: 11 })).toBe(1);
    expect(target.counter).toBe(4);
    expect(target.counter_bus_id).toBe(10);
});

test("snapshotCounter restores value and delta while the bus id is unchanged", () => {
    const target = makeTarget(5, 10);
    const snapshot = snapshotCounter(target, "counter");
    target.counter = 0;
    snapshot.restore();
    expect(target.counter).toBe(5);
    target.counter = 0;
    snapshot.restoreDelta(2);
    expect(target.counter).toBe(2);
    snapshot.restoreDelta(-4);
    expect(target.counter).toBe(0); // clamped at the default floor
});

test("snapshotCounter skips restores after a newer absolute snapshot landed", () => {
    const target = makeTarget(5, 10);
    const snapshot = snapshotCounter(target, "counter");
    target.counter = 0;
    applyCounterAbsolute(target, "counter", 8, 11);
    snapshot.restore();
    expect(target.counter).toBe(8);
    snapshot.restoreDelta(1);
    expect(target.counter).toBe(8);
    expect(target.counter_bus_id).toBe(11);
});
