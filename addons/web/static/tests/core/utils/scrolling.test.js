// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { animationFrame, microTick, runAllTimers } from "@odoo/hoot-mock";
import { scrollTo } from "@web/core/utils/dom/scrolling";

describe.current.tags("headless");

/**
 * Builds a vertically-scrollable container whose #target sits below the fold,
 * so `scrollTo` has to perform an actual scroll.
 */
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

test("resolves immediately when no scroll is needed", async () => {
    const { scrollable, target } = makeScrollable();
    scrollable.scrollTop = 500; // bring the target into view beforehand
    let resolved = false;
    scrollTo(target, { scrollable })?.then(() => (resolved = true));
    await microTick();
    await microTick();
    expect(resolved).toBe(true);
});

test("resolves when a scrollend event fires", async () => {
    const { scrollable, target } = makeScrollable();
    let resolved = false;
    scrollTo(target, { scrollable })?.then(() => (resolved = true));
    await microTick();
    // Resolution here (without advancing any timer) can only come from the
    // scrollend listener, not the max-duration fallback timer.
    scrollable.dispatchEvent(new Event("scrollend"));
    await microTick();
    await microTick();
    expect(resolved).toBe(true);
});

test("resolves via the max-duration timer when scrollend never fires", async () => {
    const { scrollable, target } = makeScrollable();
    let resolved = false;
    scrollTo(target, { scrollable })?.then(() => (resolved = true));
    // Never dispatch scrollend — emulates older Safari / embedded webviews that
    // don't fire it. The promise must still settle instead of hanging forever.
    await runAllTimers();
    await animationFrame();
    await microTick();
    expect(resolved).toBe(true);
});

test("does not hang when the scrollable is detached mid-scroll", async () => {
    const { scrollable, target } = makeScrollable();
    let resolved = false;
    scrollTo(target, { scrollable })?.then(() => (resolved = true));
    scrollable.remove();
    await runAllTimers();
    await animationFrame();
    await microTick();
    expect(resolved).toBe(true);
});
