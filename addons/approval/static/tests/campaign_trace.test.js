import { describe, expect, test } from "@odoo/hoot";
import { browser } from "@web/core/browser/browser";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { trace } from "@approval/common/approval_trace";

/**
 * The client half of the campaign instrumentation -- TEMPORARY, goes with it.
 *
 * Two invariants, and the first is why this file exists: the switch is DEFAULT OFF,
 * so every line the campaign adds to a user's console is a line somebody asked for.
 * The Python half is held by `tests/test_campaign_instrumentation.py`; nothing held
 * this one, which meant "it is off unless you ask" was a claim in a document.
 */

describe.current.tags("headless");

function captureConsole() {
    const said = [];
    patchWithCleanup(browser.console, {
        debug: (line) => said.push(`debug ${line}`),
        info: (line) => said.push(`info ${line}`),
    });
    return said;
}

function askFor(value) {
    // The switch is read once and memoised, so each test needs its own module
    // state: the URL is the only input the trace module re-reads per resolution.
    patchWithCleanup(browser, {
        location: {
            ...browser.location,
            search: value ? `?approval_trace=${value}` : "",
        },
    });
    trace.forget();
}

test("says nothing at all unless a target was asked for", () => {
    const said = captureConsole();
    askFor("");
    trace.event("button", "loaded", { model: "res.partner" });
    trace.note("service", "flushed", { specs: 3 });
    expect(said).toEqual([]);
    expect(trace.on("button")).toBe(false);
});

test("one named target speaks and the others stay quiet", () => {
    const said = captureConsole();
    askFor("button");
    trace.event("button", "loaded", { model: "res.partner", gated: true });
    trace.event("service", "flushed", { specs: 3 });
    expect(said).toEqual(["debug approval.button loaded model=res.partner gated=true"]);
});

test("the wildcard asks for every target", () => {
    const said = captureConsole();
    askFor("all");
    trace.event("button", "loaded", {});
    trace.note("service", "flushed", { specs: 2 });
    expect(said).toEqual([
        "debug approval.button loaded",
        "info approval.service flushed specs=2",
    ]);
});

test("values render the way the Python half renders them", () => {
    const said = captureConsole();
    askFor("all");
    trace.event("button", "state", {
        res_id: false,
        steps: [1, 2, 3],
        request: { id: 7, state: "pending" },
        reason: "two words",
        missing: null,
    });
    expect(said[0]).toBe(
        "debug approval.button state res_id=false steps=[1,2,3] " +
            'request={id:7,state:pending} reason="two words" missing=null',
    );
});

test("a span reports how long it took and whether it rejected", async () => {
    const said = captureConsole();
    askFor("button");
    await trace.span("button", "decided", { approve: true }, async () => "done");
    expect(said[0]).toMatch(
        /^debug approval\.button decided approve=true ms=[\d.]+ r=ok$/,
    );
    await expect(
        trace.span("button", "decided", {}, async () => {
            throw new TypeError("no");
        }),
    ).rejects.toThrow();
    expect(said[1]).toMatch(/r=rejected:TypeError$/);
});

test("a span that is not asked for still returns what it wrapped", async () => {
    const said = captureConsole();
    askFor("");
    expect(await trace.span("button", "decided", {}, async () => 42)).toBe(42);
    expect(said).toEqual([]);
});
