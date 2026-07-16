// @ts-check

import { describe, expect, mockSendBeacon, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { reportJsError } from "@web/core/errors/error_beacon";

describe.current.tags("headless");

const ENDPOINT = "/web/observability/js_error";

/**
 * Install a sendBeacon spy that records each (url, parsed-payload) and reports
 * success. The mocked navigator.sendBeacon IS this callback, and its return
 * value is what ``reportJsError`` coerces to its boolean result.
 *
 * @returns {{ calls: { url: string, blob: Blob }[] }}
 */
function spyBeacon() {
    const calls = [];
    mockSendBeacon((url, blob) => {
        calls.push({ url, blob });
        return true;
    });
    return { calls };
}

/** @param {Blob} blob */
async function payloadOf(blob) {
    return JSON.parse(await blob.text());
}

// Every test uses a UNIQUE message: the throttle ``seen`` set is module-level
// and lives for the whole page (test run), so a reused (message,line,col)
// would be swallowed by an earlier test's entry.

test("reportJsError: an empty message is dropped without touching sendBeacon", () => {
    const { calls } = spyBeacon();
    expect(reportJsError({ message: "" })).toBe(false);
    expect(reportJsError({})).toBe(false);
    expect(reportJsError({ message: null })).toBe(false);
    expect(calls).toHaveLength(0);
});

test("reportJsError: a fresh error queues a beacon to the endpoint", async () => {
    const { calls } = spyBeacon();
    const ok = reportJsError({
        message: "beacon-fresh",
        line: 12,
        col: 4,
        filename: "foo.js",
        stack: "at foo (foo.js:12:4)",
    });
    expect(ok).toBe(true);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(ENDPOINT);
    expect(calls[0].blob.type).toBe("application/json");
    const payload = await payloadOf(calls[0].blob);
    expect(payload.message).toBe("beacon-fresh");
    expect(payload.line).toBe(12);
    expect(payload.col).toBe(4);
    expect(payload.filename).toBe("foo.js");
    expect(payload.stack).toBe("at foo (foo.js:12:4)");
    expect(payload.kind).toBe("error");
});

test("reportJsError: the same (message,line,col) is throttled after the first", () => {
    const { calls } = spyBeacon();
    expect(reportJsError({ message: "beacon-dup", line: 1, col: 1 })).toBe(true);
    expect(reportJsError({ message: "beacon-dup", line: 1, col: 1 })).toBe(false);
    expect(reportJsError({ message: "beacon-dup", line: 1, col: 1 })).toBe(false);
    expect(calls).toHaveLength(1);
});

test("reportJsError: same message on a different line/col is a distinct beacon", () => {
    const { calls } = spyBeacon();
    expect(reportJsError({ message: "beacon-key", line: 1, col: 1 })).toBe(true);
    expect(reportJsError({ message: "beacon-key", line: 2, col: 1 })).toBe(true);
    expect(reportJsError({ message: "beacon-key", line: 1, col: 2 })).toBe(true);
    expect(calls).toHaveLength(3);
});

test("reportJsError: kind is normalized to error | unhandledrejection", async () => {
    const { calls } = spyBeacon();
    reportJsError({ message: "beacon-kind-rej", kind: "unhandledrejection" });
    reportJsError({ message: "beacon-kind-bogus", kind: /** @type {any} */ ("weird") });
    expect((await payloadOf(calls[0].blob)).kind).toBe("unhandledrejection");
    // Any non-"unhandledrejection" kind collapses to "error".
    expect((await payloadOf(calls[1].blob)).kind).toBe("error");
});

test("reportJsError: line/col are coerced to integers, filename defaults to ''", async () => {
    const { calls } = spyBeacon();
    reportJsError({
        message: "beacon-coerce",
        line: 9.9,
        col: /** @type {any} */ ("7"),
    });
    const a = await payloadOf(calls[0].blob);
    expect(a.line).toBe(9); // 9.9 | 0
    expect(a.col).toBe(7); // "7" | 0
    expect(a.filename).toBe("");
    expect(a.stack).toBe(""); // no stack provided

    reportJsError({ message: "beacon-coerce-2" });
    const b = await payloadOf(calls[1].blob);
    expect(b.line).toBe(0); // undefined | 0
    expect(b.col).toBe(0);
});

test("reportJsError: message and stack are capped at 4096 chars", async () => {
    const { calls } = spyBeacon();
    const longMessage = "m".repeat(5000);
    const longStack = "s".repeat(5000);
    reportJsError({ message: longMessage, stack: longStack });
    const payload = await payloadOf(calls[0].blob);
    expect(payload.message).toHaveLength(4096);
    expect(payload.stack).toHaveLength(4096);
});

test("reportJsError: phase reflects odoo.isReady (pre_boot vs post_boot)", async () => {
    const { calls } = spyBeacon();
    patchWithCleanup(odoo, { isReady: true });
    reportJsError({ message: "beacon-phase-post" });
    expect((await payloadOf(calls[0].blob)).phase).toBe("post_boot");

    patchWithCleanup(odoo, { isReady: false });
    reportJsError({ message: "beacon-phase-pre" });
    expect((await payloadOf(calls[1].blob)).phase).toBe("pre_boot");
});

test("reportJsError: never throws and returns false when sendBeacon is unavailable", () => {
    // No mockSendBeacon → the mocked navigator.sendBeacon throws
    // (throwNotImplemented). Telemetry must swallow it and report failure.
    expect(() => reportJsError({ message: "beacon-nobeacon" })).not.toThrow();
    expect(reportJsError({ message: "beacon-nobeacon-2" })).toBe(false);
});

test("reportJsError: a sendBeacon that rejects the payload returns false", () => {
    // UA quota exceeded → sendBeacon returns false; reportJsError mirrors it.
    mockSendBeacon(() => false);
    expect(reportJsError({ message: "beacon-quota" })).toBe(false);
});
