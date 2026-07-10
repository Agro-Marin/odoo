// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    InvalidUrgentSaveTransitionError,
    UrgentSaveCoordinator,
} from "@web/model/relational_model/urgent_save_coordinator";

describe.current.tags("headless");

test("new instance starts idle and isActive=false", () => {
    const coord = new UrgentSaveCoordinator();
    expect(coord.status).toBe("idle");
    expect(coord.isActive).toBe(false);
});

test("run() flips status active during fn, idle after", async () => {
    const coord = new UrgentSaveCoordinator();
    let snapshot;
    const result = await coord.run(async () => {
        snapshot = coord.isActive;
        return 42;
    });
    expect(snapshot).toBe(true);
    expect(result).toBe(42);
    expect(coord.isActive).toBe(false);
});

test("run() restores status even when fn throws", async () => {
    const coord = new UrgentSaveCoordinator();
    await expect(
        coord.run(async () => {
            throw new Error("boom");
        }),
    ).rejects.toThrow("boom");
    expect(coord.isActive).toBe(false);
});

test("run() fires WILL_SAVE_URGENTLY on the bus at entry", async () => {
    const events = [];
    const bus = { trigger: (event, payload) => events.push({ event, payload }) };
    const coord = new UrgentSaveCoordinator(bus);
    await coord.run(async () => {});
    expect(events.length).toBe(1);
    expect(events[0].event).toBe("WILL_SAVE_URGENTLY");
});

test("nested run() throws InvalidUrgentSaveTransitionError", async () => {
    const coord = new UrgentSaveCoordinator();
    await expect(
        coord.run(async () => {
            await coord.run(async () => {});
        }),
    ).rejects.toBeInstanceOf(InvalidUrgentSaveTransitionError);
});

test("awaitUnlessUrgent resolves promise normally when idle", async () => {
    const coord = new UrgentSaveCoordinator();
    const result = await coord.awaitUnlessUrgent(Promise.resolve("real value"));
    expect(result).toBe("real value");
});

test("awaitUnlessUrgent returns undefined when active (does not await)", async () => {
    const coord = new UrgentSaveCoordinator();
    // Promise that would block forever if awaited
    let resolved = false;
    const slow = new Promise((r) => {
        // Resolves asynchronously via setTimeout, so we can detect whether it was awaited.
        setTimeout(() => {
            resolved = true;
            r("eventually");
        }, 0);
    });
    await coord.run(async () => {
        const result = await coord.awaitUnlessUrgent(slow);
        expect(result).toBe(undefined);
        expect(resolved).toBe(false); // we did NOT wait for it
    });
});

test("awaitUnlessUrgent accepts undefined promise without throwing", async () => {
    const coord = new UrgentSaveCoordinator();
    const result = await coord.awaitUnlessUrgent(undefined);
    expect(result).toBe(undefined);
});

test("unlessUrgent invokes fn when idle and returns its value", async () => {
    const coord = new UrgentSaveCoordinator();
    let called = false;
    const result = coord.unlessUrgent(() => {
        called = true;
        return "fired";
    });
    expect(called).toBe(true);
    expect(result).toBe("fired");
});

test("unlessUrgent does NOT invoke fn when active", async () => {
    const coord = new UrgentSaveCoordinator();
    await coord.run(async () => {
        let called = false;
        const result = coord.unlessUrgent(() => {
            called = true;
            return "should not happen";
        });
        expect(called).toBe(false);
        expect(result).toBe(undefined);
    });
});

test("unlessUrgent propagates promise return when idle", async () => {
    const coord = new UrgentSaveCoordinator();
    const result = await coord.unlessUrgent(async () => "async value");
    expect(result).toBe("async value");
});
