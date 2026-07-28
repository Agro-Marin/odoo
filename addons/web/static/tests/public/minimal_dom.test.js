// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { makeAsyncHandler, makeButtonHandler } from "@web/public/minimal_dom";

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

test("makeButtonHandler leaves a pre-existing pe-none in place", async () => {
    const buttonEl = document.createElement("button");
    buttonEl.className = "btn pe-none";
    getFixture().appendChild(buttonEl);
    const handler = makeButtonHandler(() => {});
    buttonEl.addEventListener("click", handler);
    buttonEl.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await animationFrame();
    await animationFrame();
    expect(buttonEl).toHaveClass("pe-none");
});

test("makeButtonHandler re-enables a button that was clickable", async () => {
    const buttonEl = document.createElement("button");
    buttonEl.className = "btn";
    getFixture().appendChild(buttonEl);
    const handler = makeButtonHandler(() => {});
    buttonEl.addEventListener("click", handler);
    buttonEl.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await animationFrame();
    await animationFrame();
    expect(buttonEl).not.toHaveClass("pe-none");
});
