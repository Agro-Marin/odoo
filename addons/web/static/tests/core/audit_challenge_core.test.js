// @ts-check

/**
 * AUDIT CHALLENGE — executable proofs for core-layer findings.
 *
 * Each test asserts the CORRECT behaviour, so it fails against the current
 * implementation and passes once the finding is fixed.
 *
 * NOT covered here, deliberately: `Domain.combine` treats `[]` as the identity
 * of both AND and OR, but `[]` is TRUE, so it is the identity of AND only.
 * Executed against the server for ground truth:
 *     Domain.OR([])        -> [(0,'=',1)]  FALSE   |  JS: []          TRUE
 *     Domain.OR([[], X])   -> [(1,'=',1)]  TRUE    |  JS: X
 * Correcting the primitive was tried and reverted: four call sites in `web`
 * alone use `Domain.or([...])` to mean "contributes no constraint" and then AND
 * the result, so the corrected semantics turned "match everything" into "match
 * nothing" (grouped list expansion, date filters) or injected a stray TRUE leaf
 * into exported domains. Fixing this requires auditing every OR call site —
 * including enterprise/agromarin — or introducing an explicit API for the
 * "no constraint" idiom. It is a real divergence, not a safe drop-in fix.
 */

import { describe, expect, test } from "@odoo/hoot";
import { advanceTime, Deferred } from "@odoo/hoot-mock";
import { assets } from "@web/core/assets";
import { setRecurringAnimationFrame } from "@web/core/utils/timing";

describe.current.tags("headless");

describe("setRecurringAnimationFrame", () => {
    test("stop() called from inside the callback halts the loop", async () => {
        let ticks = 0;
        const stop = setRecurringAnimationFrame(() => {
            ticks++;
            if (ticks >= 2) {
                stop();
            }
        });
        await advanceTime(1000);
        // Currently the handler re-schedules unconditionally after invoking the
        // callback, so stop() cancels an already-fired handle and the loop runs
        // forever, retaining its closure for the page lifetime.
        expect(ticks).toBe(2);
        stop();
    });
});

describe("assets loading lifecycle", () => {
    test("loadJS settles (rejects) when the page is hidden mid-load", async () => {
        const settled = new Deferred();
        const url = `/web/static/audit_challenge_never_loads_${Date.now()}.js`;
        const promise = assets.loadJS(url);
        promise.then(
            () => settled.resolve("resolved"),
            () => settled.resolve("rejected"),
        );
        // Simulate bfcache suspension before the <script> fires load/error.
        window.dispatchEvent(new Event("pagehide"));
        const outcome = await Promise.race([
            settled,
            advanceTime(5000).then(() => "PENDING FOREVER"),
        ]);
        // loadESMBundle's pagehide arm rejects; loadJS/loadCSS only remove the
        // listeners and evict the cache, leaving the caller's promise pending.
        expect(outcome).toBe("rejected");
    });
});
