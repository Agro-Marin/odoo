// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { animationFrame, microTick, runAllTimers } from "@odoo/hoot-mock";
import { scrollTo } from "@web/core/utils/dom/scrolling";

describe.current.tags("headless");

function makeScrollable() {
    const fixture = getFixture();
    fixture.innerHTML = `
        <div id="scrollable" style="height: 100px; overflow-y: auto;">
            <div style="height: 500px;"></div>
            <div id="target" style="height: 50px;">target</div>
            <div style="height: 500px;"></div>
        </div>
    `;
    return {
        scrollable: /** @type {HTMLElement} */ (fixture.querySelector("#scrollable")),
        target: /** @type {HTMLElement} */ (fixture.querySelector("#target")),
    };
}

async function settlesOnMicrotasks(promise) {
    let settled = false;
    promise?.then(() => (settled = true));
    for (let i = 0; i < 20; i++) {
        await microTick();
    }
    return settled;
}

test("resolves immediately when no scroll is needed", async () => {
    const { scrollable, target } = makeScrollable();
    scrollable.scrollTop = 500;
    expect(await settlesOnMicrotasks(scrollTo(target, { scrollable }))).toBe(true);
    expect(scrollable.scrollTop).toBe(500);
});

test("does NOT resolve on microtasks alone when a scroll is needed", async () => {
    const { scrollable, target } = makeScrollable();
    expect(await settlesOnMicrotasks(scrollTo(target, { scrollable }))).toBe(false);
    expect(scrollable.scrollTop).toBe(450);
});

test("does not report a smooth scroll as settled before it starts", async () => {
    const { scrollable, target } = makeScrollable();
    const settled = await settlesOnMicrotasks(
        scrollTo(target, { scrollable, behavior: "smooth" }),
    );
    expect([scrollable.scrollTop, settled]).toEqual([0, false]);
});

test("resolves when a scrollend event fires", async () => {
    const { scrollable, target } = makeScrollable();
    let resolved = false;
    scrollTo(target, { scrollable })?.then(() => (resolved = true));
    await microTick();
    expect(scrollable.scrollTop).toBe(450);
    scrollable.dispatchEvent(new Event("scrollend"));
    await microTick();
    await microTick();
    expect(resolved).toBe(true);
});

test("resolves via the max-duration timer when scrollend never fires", async () => {
    const { scrollable, target } = makeScrollable();
    let resolved = false;
    scrollTo(target, { scrollable })?.then(() => (resolved = true));
    expect(await settlesOnMicrotasks(Promise.resolve())).toBe(true);
    expect(resolved).toBe(false);
    await runAllTimers();
    await animationFrame();
    await microTick();
    expect(resolved).toBe(true);
});

test("does not hang when the scrollable is detached mid-scroll", async () => {
    const { scrollable, target } = makeScrollable();
    let resolved = false;
    scrollTo(target, { scrollable })?.then(() => (resolved = true));
    await microTick();
    expect(scrollable.scrollTop).toBe(450);
    scrollable.remove();
    await runAllTimers();
    await animationFrame();
    await microTick();
    expect(resolved).toBe(true);
});
