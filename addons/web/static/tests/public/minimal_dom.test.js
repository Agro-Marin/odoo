// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { makeAsyncHandler } from "@web/public/minimal_dom";

describe.current.tags("headless");

test("makeAsyncHandler hands the failure to its caller", async () => {
    // the lock can only be released by observing the outcome, so the returned
    // promise is the sole channel: whoever discards it owns its errors
    const handler = makeAsyncHandler(async () => {
        throw new Error("caller channel boom");
    });
    await expect(handler(new Event("click"))).rejects.toThrow("caller channel boom");
});

test("makeAsyncHandler unlocks again after a failure", async () => {
    let calls = 0;
    const handler = makeAsyncHandler(async () => {
        calls++;
        throw new Error("boom");
    });
    handler(new Event("click"))?.catch(() => {});
    await animationFrame();
    handler(new Event("click"))?.catch(() => {});
    await animationFrame();
    expect(calls).toBe(2);
});
