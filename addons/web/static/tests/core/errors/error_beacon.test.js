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

test("reportJsError: kind passes through for every kind the server accepts", async () => {
    const { calls } = spyBeacon();
    reportJsError({ message: "beacon-kind-err", kind: "error" });
    reportJsError({ message: "beacon-kind-rej", kind: "unhandledrejection" });
    reportJsError({ message: "beacon-kind-svc", kind: "service_start" });
    reportJsError({ message: "beacon-kind-asset", kind: "asset_load_error" });
    reportJsError({ message: "beacon-kind-rebind", kind: "module_rebind" });
    reportJsError({ message: "beacon-kind-bogus", kind: /** @type {any} */ ("weird") });
    // The five kinds observability.py::js_error accepted when this was written.
    // Nothing couples the two, so widening the server's tuple will not fail here.
    expect((await payloadOf(calls[0].blob)).kind).toBe("error");
    expect((await payloadOf(calls[1].blob)).kind).toBe("unhandledrejection");
    expect((await payloadOf(calls[2].blob)).kind).toBe("service_start");
    expect((await payloadOf(calls[3].blob)).kind).toBe("asset_load_error");
    expect((await payloadOf(calls[4].blob)).kind).toBe("module_rebind");
    // The fallback still guards typos — widening the set must not make it a
    // pass-through, or a misspelled kind becomes a category of its own.
    expect((await payloadOf(calls[5].blob)).kind).toBe("error");
});

test("reportJsError: line/col are coerced to integers, filename defaults to ''", async () => {
    const { calls } = spyBeacon();
    reportJsError({
        message: "beacon-coerce",
        line: 9.9,
        col: /** @type {any} */ ("7"),
    });
    const a = await payloadOf(calls[0].blob);
    expect(a.line).toBe(9);
    expect(a.col).toBe(7);
    expect(a.filename).toBe("");
    expect(a.stack).toBe("");

    reportJsError({ message: "beacon-coerce-2" });
    const b = await payloadOf(calls[1].blob);
    expect(b.line).toBe(0);
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
    expect(() => reportJsError({ message: "beacon-nobeacon" })).not.toThrow();
    expect(reportJsError({ message: "beacon-nobeacon-2" })).toBe(false);
});

test("reportJsError: a sendBeacon that rejects the payload returns false", () => {
    mockSendBeacon(() => false);
    expect(reportJsError({ message: "beacon-quota" })).toBe(false);
});

test("reportJsError: the cause chain is serialized into the payload", async () => {
    const { calls } = spyBeacon();
    const inner = new TypeError("x is undefined");
    const outer = new Error("owl lifecycle", { cause: inner });
    reportJsError({ message: "beacon-cause", cause: outer.cause });
    const payload = await payloadOf(calls[0].blob);
    expect(payload.cause).toBe("Caused by: TypeError: x is undefined");
});

test("reportJsError: a multi-level cause chain keeps every level in order", async () => {
    const { calls } = spyBeacon();
    const root = new RangeError("root");
    const mid = new Error("mid", { cause: root });
    reportJsError({ message: "beacon-cause-chain", cause: mid });
    const payload = await payloadOf(calls[0].blob);
    expect(payload.cause).toBe("Caused by: Error: mid\nCaused by: RangeError: root");
});

test("reportJsError: a cause chain deeper than the cap stops at the cap", async () => {
    const { calls } = spyBeacon();
    let deepest = new Error("level-0");
    for (let i = 1; i < 20; i++) {
        deepest = new Error(`level-${i}`, { cause: deepest });
    }
    reportJsError({ message: "beacon-cause-deep", cause: deepest });
    const payload = await payloadOf(calls[0].blob);
    // 8 levels max — without the cap a long chain would crowd out the fields
    // that identify where the failure happened.
    expect(payload.cause.split("\n")).toHaveLength(8);
});

test("reportJsError: a cyclic cause chain terminates instead of spinning", async () => {
    const { calls } = spyBeacon();
    const a = new Error("a");
    const b = new Error("b", { cause: a });
    /** @type {any} */ (a).cause = b;
    expect(() =>
        reportJsError({ message: "beacon-cause-cycle", cause: b }),
    ).not.toThrow();
    const payload = await payloadOf(calls[0].blob);
    expect(payload.cause).toInclude("[circular]");
});

test("reportJsError: non-Error causes are serialized without throwing", async () => {
    const { calls } = spyBeacon();
    reportJsError({ message: "beacon-cause-str", cause: "just a string" });
    reportJsError({ message: "beacon-cause-obj", cause: { code: 500 } });
    reportJsError({ message: "beacon-cause-num", cause: 42 });
    expect((await payloadOf(calls[0].blob)).cause).toBe("Caused by: just a string");
    expect((await payloadOf(calls[1].blob)).cause).toBe('Caused by: {"code":500}');
    expect((await payloadOf(calls[2].blob)).cause).toBe("Caused by: 42");
});

test("reportJsError: an unserializable cause degrades to a placeholder", async () => {
    const { calls } = spyBeacon();
    // BigInt has no JSON representation, so JSON.stringify throws here.
    reportJsError({ message: "beacon-cause-bigint", cause: { n: 1n } });
    const payload = await payloadOf(calls[0].blob);
    expect(payload.cause).toBe("Caused by: [unserializable]");
});

test("reportJsError: no cause yields an empty field, not a missing one", async () => {
    const { calls } = spyBeacon();
    reportJsError({ message: "beacon-cause-none" });
    const payload = await payloadOf(calls[0].blob);
    expect(payload.cause).toBe("");
});

test("reportJsError: the cause chain is capped at 4096 chars", async () => {
    const { calls } = spyBeacon();
    reportJsError({ message: "beacon-cause-cap", cause: "c".repeat(5000) });
    expect((await payloadOf(calls[0].blob)).cause).toHaveLength(4096);
});

test("reportJsError: same message and position but a different stack is distinct", () => {
    const { calls } = spyBeacon();
    // The regression this guards: OWL reports every lifecycle failure with one
    // generic message at 0:0, so these two used to collapse into one beacon.
    const message = "An error occured in the owl lifecycle";
    expect(reportJsError({ message, stack: "at ComponentA (a.js:1:1)" })).toBe(true);
    expect(reportJsError({ message, stack: "at ComponentB (b.js:2:2)" })).toBe(true);
    expect(calls).toHaveLength(2);
});

test("reportJsError: an exact repeat including the stack is still throttled", () => {
    const { calls } = spyBeacon();
    const info = { message: "beacon-dup-stack", stack: "at same (same.js:1:1)" };
    expect(reportJsError({ ...info })).toBe(true);
    expect(reportJsError({ ...info })).toBe(false);
    expect(calls).toHaveLength(1);
});

test("reportJsError: same message and stack but a different cause is distinct", () => {
    const { calls } = spyBeacon();
    // The real OWL shape: the wrapper is built inside handleError, so its stack
    // is the scheduler frames — identical for two unrelated component crashes
    // flushed in the same tick. Only the cause tells them apart.
    const shared = {
        message: "An error occured in the owl lifecycle",
        stack: "at handleError\n at Fiber.complete\n at Scheduler.flush",
    };
    expect(reportJsError({ ...shared, cause: new TypeError("component A") })).toBe(
        true,
    );
    expect(reportJsError({ ...shared, cause: new TypeError("component B") })).toBe(
        true,
    );
    expect(reportJsError({ ...shared, cause: new TypeError("component A") })).toBe(
        false,
    );
    expect(calls).toHaveLength(2);
});

test("reportJsError: a nested object cause is elided, not walked", async () => {
    const { calls } = spyBeacon();
    const deep = { level: 1, child: { level: 2, child: { level: 3 } } };
    reportJsError({ message: "beacon-cause-elide", cause: deep });
    const payload = await payloadOf(calls[0].blob);
    expect(payload.cause).toBe('Caused by: {"level":1,"child":"[object]"}');
});
test("reportJsError: an explicit phase overrides the odoo.isReady default", async () => {
    const { calls } = spyBeacon();
    patchWithCleanup(odoo, { isReady: true }); // would otherwise be post_boot
    reportJsError({ message: "beacon-phase-override", phase: "boot_mount_failed" });
    expect((await payloadOf(calls[0].blob)).phase).toBe("boot_mount_failed");
});

test("reportJsError: dedup:false beacons every occurrence", () => {
    const { calls } = spyBeacon();
    expect(reportJsError({ message: "beacon-every", dedup: false })).toBe(true);
    expect(reportJsError({ message: "beacon-every", dedup: false })).toBe(true);
    expect(calls).toHaveLength(2);
});
