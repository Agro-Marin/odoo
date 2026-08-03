// @ts-check

import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { webVitalsService } from "@web/core/network/web_vitals/web_vitals_service";

describe.current.tags("headless");

/**
 * `toBeCloseTo`'s `margin` DEFAULTS TO 1, which for CLS scores (0-5) accepts
 * essentially any value — a tolerance that silently passed these tests against
 * the very implementation they exist to reject. Always pass an explicit margin.
 */
const TOL = 1e-9;

/**
 * Minimal stand-in for `PerformanceObserver`: records what it was asked to
 * observe and lets a test push entries into the service's callback.
 */
class FakePerformanceObserver {
    /** @type {FakePerformanceObserver[]} */
    static instances = [];

    /** @param {(list: { getEntries: () => any[] }) => void} callback */
    constructor(callback) {
        this._callback = callback;
        this.type = null;
        this.disconnected = false;
        FakePerformanceObserver.instances.push(this);
    }

    /** @param {{ type: string }} options */
    observe(options) {
        this.type = options.type;
    }

    disconnect() {
        this.disconnected = true;
    }

    /** @param {any[]} entries */
    emit(entries) {
        this._callback({ getEntries: () => entries });
    }
}

/**
 * @param {string} type
 * @returns {FakePerformanceObserver}
 */
function observerFor(type) {
    const observer = FakePerformanceObserver.instances.find((o) => o.type === type);
    if (!observer) {
        throw new Error(`no observer registered for "${type}"`);
    }
    return observer;
}

/**
 * A `layout-shift` entry as the browser reports it.
 * @param {number} startTime
 * @param {number} value
 * @param {boolean} [hadRecentInput]
 */
function shift(startTime, value, hadRecentInput = false) {
    return { startTime, value, hadRecentInput };
}

/** @type {any[]} */
let beacons;
/** @type {{ destroy: () => void } | undefined} */
let service;

beforeEach(() => {
    beacons = [];
    FakePerformanceObserver.instances = [];
    patchWithCleanup(browser, {
        PerformanceObserver: /** @type {any} */ (FakePerformanceObserver),
    });
    patchWithCleanup(browser.navigator, {
        sendBeacon: (/** @type {string} */ url, /** @type {Blob} */ blob) => {
            beacons.push({ url, blob });
            return true;
        },
    });
    service = /** @type {any} */ (webVitalsService.start());
});

afterEach(() => {
    service?.destroy();
});

/**
 * Flush via `pagehide` and return the payload of the last beacon.
 * @returns {Promise<any>}
 */
async function flush() {
    browser.dispatchEvent(new Event("pagehide"));
    const last = beacons.at(-1);
    return last ? JSON.parse(await last.blob.text()) : undefined;
}

test("CLS is the largest session window, not the lifetime sum", async () => {
    // Two bursts separated by a >1s gap. The sum is 0.8; CLS is the bigger
    // burst, 0.6. Summing everything is what the service used to report and is
    // unbounded across a long single-page session.
    observerFor("layout-shift").emit([
        shift(0, 0.1),
        shift(500, 0.1),
        // >1s gap closes the first window
        shift(3000, 0.3),
        shift(3500, 0.3),
    ]);

    const payload = await flush();
    expect(payload.cls).toBeCloseTo(0.6, {
        margin: TOL,
        message: "the larger of the two bursts; their SUM would be 0.8",
    });
});

test("a window also closes after 5s even with no 1s gap", async () => {
    // Shifts every 900ms never open a gap, so only the 5s span cap can end the
    // window. Without it a steady drizzle of shifts accumulates forever.
    observerFor("layout-shift").emit([
        shift(0, 0.1),
        shift(900, 0.1),
        shift(1800, 0.1),
        shift(2700, 0.1),
        shift(3600, 0.1),
        shift(4500, 0.1),
        // 5400 - 0 >= 5000: new window despite the 900ms gap
        shift(5400, 0.1),
        shift(6300, 0.1),
    ]);

    const payload = await flush();
    expect(payload.cls).toBeCloseTo(0.6, { margin: TOL });
});

test("entries following recent input are excluded", async () => {
    observerFor("layout-shift").emit([
        shift(0, 0.1),
        shift(100, 5, true),
        shift(200, 0.1),
    ]);

    const payload = await flush();
    expect(payload.cls).toBeCloseTo(0.2, { margin: TOL });
});

test("a page whose every shift was input-triggered reports cls: 0, not nothing", async () => {
    // Omitting the key reads downstream as "not measured"; 0 is the real,
    // meaningful answer.
    observerFor("layout-shift").emit([shift(0, 0.4, true), shift(100, 0.2, true)]);

    const payload = await flush();
    expect(payload.cls).toBe(0);
});

test("the reported value never decreases when a later window is smaller", async () => {
    observerFor("layout-shift").emit([shift(0, 0.4)]);
    observerFor("layout-shift").emit([shift(9000, 0.05)]);

    const payload = await flush();
    expect(payload.cls).toBeCloseTo(0.4, { margin: TOL });
});

test("a long session stays inside the server's accepted CLS range", async () => {
    // `_clamp_cls` in controllers/observability.py DROPS anything above 5.0, so
    // an accumulating total eventually stopped being recorded at all. 400 small
    // shifts spread over an hour must still report a small windowed value.
    const entries = [];
    for (let i = 0; i < 400; i++) {
        entries.push(shift(i * 9000, 0.05));
    }
    observerFor("layout-shift").emit(entries);

    const payload = await flush();
    expect(payload.cls).toBeCloseTo(0.05, { margin: TOL });
    expect(payload.cls).toBeLessThan(5);
});

test("no beacon is sent when nothing was measured", async () => {
    // `metrics` is empty: TTFB may be absent in the fixture and no observer
    // fired. `flush()` must not post an payload of nothing.
    const before = beacons.length;
    browser.dispatchEvent(new Event("pagehide"));
    if (beacons.length > before) {
        const payload = JSON.parse(await beacons.at(-1).blob.text());
        expect(Object.keys(payload).length).toBeGreaterThan(3);
    } else {
        expect(beacons.length).toBe(before);
    }
});

test("an unchanged metric set is not beaconed twice", async () => {
    observerFor("layout-shift").emit([shift(0, 0.2)]);
    await flush();
    const afterFirst = beacons.length;
    browser.dispatchEvent(new Event("pagehide"));
    expect(beacons.length).toBe(afterFirst);
});

test("destroy detaches the observers and the page listeners", async () => {
    observerFor("layout-shift").emit([shift(0, 0.2)]);
    /** @type {any} */ (service).destroy();
    service = undefined;

    expect(observerFor("layout-shift").disconnected).toBe(true);
    const before = beacons.length;
    browser.dispatchEvent(new Event("pagehide"));
    expect(beacons.length).toBe(before);
});

test("a page with no layout shift still reports cls, rather than omitting it", async () => {
    // A buffered PerformanceObserver never invokes its callback when no entry
    // matches, so `cls` used to be absent here — indistinguishable downstream
    // from "CLS was not measured", which is the confusion the unconditional
    // assignment inside the callback exists to prevent.
    observerFor("paint").emit([{ name: "first-contentful-paint", startTime: 12 }]);
    const payload = await flush();
    expect(payload.cls).toBeCloseTo(0, { margin: TOL });
});
