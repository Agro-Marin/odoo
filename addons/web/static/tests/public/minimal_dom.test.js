// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { advanceTime, animationFrame, Deferred, runAllTimers } from "@odoo/hoot-mock";
import { makeAsyncHandler, makeButtonHandler } from "@web/public/minimal_dom";

describe.current.tags("headless");

test("makeAsyncHandler hands the failure to its caller", async () => {
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
    /** @type {HTMLElement} */ (getFixture()).appendChild(buttonEl);
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
    /** @type {HTMLElement} */ (getFixture()).appendChild(buttonEl);
    const handler = makeButtonHandler(() => {});
    buttonEl.addEventListener("click", handler);
    buttonEl.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await animationFrame();
    await animationFrame();
    expect(buttonEl).not.toHaveClass("pe-none");
});

test("makeButtonHandler keeps a pre-existing pe-none across the loading effect", async () => {
    const def = new Deferred();
    const buttonEl = document.createElement("button");
    buttonEl.className = "btn pe-none";
    buttonEl.disabled = true;
    /** @type {HTMLElement} */ (getFixture()).appendChild(buttonEl);
    buttonEl.addEventListener(
        "click",
        makeButtonHandler(() => def),
    );
    buttonEl.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await advanceTime(401);
    def.resolve();
    await animationFrame();
    await animationFrame();
    expect(buttonEl).toHaveClass("pe-none");
    expect(buttonEl.disabled).toBe(true);
});

test("makeButtonHandler puts the effect on the control it is bound to", async () => {
    /** @type {HTMLElement} */ (getFixture()).innerHTML =
        `<div class="btn outer"><a class="inner">go</a></div>`;
    const outer = queryOne(".outer");
    const inner = queryOne(".inner");
    outer.addEventListener(
        "click",
        makeButtonHandler(() => {}),
    );
    inner.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(outer).toHaveClass("pe-none");
    expect(inner).not.toHaveClass("pe-none");
});

test("makeButtonHandler still finds the control when delegated", async () => {
    /** @type {HTMLElement} */ (getFixture()).innerHTML =
        `<div class="host"><button class="btn target"><span>go</span></button></div>`;
    const host = queryOne(".host");
    const button = queryOne(".target");
    host.addEventListener(
        "click",
        makeButtonHandler(() => {}),
    );
    queryOne("span").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(button).toHaveClass("pe-none");
    expect(host).not.toHaveClass("pe-none");
});

test("makeButtonHandler arms no loading timer that outlives its handler", async () => {
    const buttonEl = document.createElement("button");
    /** @type {HTMLElement} */ (getFixture()).append(buttonEl);
    buttonEl.addEventListener(
        "click",
        makeButtonHandler(() => Promise.resolve()),
    );
    await runAllTimers();
    buttonEl.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await animationFrame();
    await animationFrame();
    expect(await runAllTimers()).toBe(0);
});

test("makeButtonHandler still shows the debounced effect for a slow handler", async () => {
    const def = new Deferred();
    const buttonEl = document.createElement("button");
    buttonEl.className = "btn";
    /** @type {HTMLElement} */ (getFixture()).append(buttonEl);
    buttonEl.addEventListener(
        "click",
        makeButtonHandler(() => def),
    );
    buttonEl.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await animationFrame();
    expect(buttonEl).toHaveClass("pe-none");
    await advanceTime(401);
    expect(buttonEl.querySelector(".fa-spin")).not.toBe(null);
    def.resolve();
    await animationFrame();
    await animationFrame();
    expect(buttonEl.querySelector(".fa-spin")).toBe(null);
});
