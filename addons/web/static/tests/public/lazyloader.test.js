// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import lazyloader from "@web/public/lazyloader";

describe.current.tags("headless");

const SCRIPT_LOAD_TIMEOUT_DELAY = 60000;

/**
 * Creates a *detached* lazy script node: a script element outside the DOM
 * never fetches (setting `src` on it is inert), so tests can dispatch "load"
 * and "error" deterministically without any network involvement.
 *
 * @param {string} name
 * @returns {HTMLScriptElement}
 */
function makeLazyScript(name) {
    const script = document.createElement("script");
    script.setAttribute("data-src", `/web/static/tests/${name}`);
    return script;
}

test("success path: scripts load sequentially, in order", async () => {
    const script1 = makeLazyScript("lazy_1.js");
    const script2 = makeLazyScript("lazy_2.js");
    let doneCalls = 0;
    lazyloader.loadScripts([script1, script2], 0, () => doneCalls++);

    expect(script1.src).toInclude("lazy_1.js");
    expect(script1.hasAttribute("data-src")).toBe(false);
    expect(script1.getAttribute("defer")).toBe("defer");
    expect(script2.src).toBe("");
    expect(doneCalls).toBe(0);

    script1.dispatchEvent(new Event("load"));
    expect(script2.src).toInclude("lazy_2.js");
    expect(doneCalls).toBe(0);

    script2.dispatchEvent(new Event("load"));
    expect(doneCalls).toBe(1);

    await advanceTime(SCRIPT_LOAD_TIMEOUT_DELAY + 1);
    expect(doneCalls).toBe(1);
});

test("a failing script logs an error and does not block the chain", async () => {
    patchWithCleanup(console, {
        error: (message) => expect.step(String(message)),
    });
    const script1 = makeLazyScript("lazy_broken.js");
    const script2 = makeLazyScript("lazy_2.js");
    let doneCalls = 0;
    lazyloader.loadScripts([script1, script2], 0, () => doneCalls++);

    script1.dispatchEvent(new Event("error"));
    expect.verifySteps([`Failed to load lazy script: ${script1.src}`]);

    expect(script2.src).toInclude("lazy_2.js");
    script2.dispatchEvent(new Event("load"));
    expect(doneCalls).toBe(1);

    await advanceTime(SCRIPT_LOAD_TIMEOUT_DELAY + 1);
    expect(doneCalls).toBe(1);
    expect.verifySteps([]);
});

test("a hung script (neither load nor error) cannot block the page forever", async () => {
    patchWithCleanup(console, {
        error: (message) => expect.step(String(message)),
    });
    const script1 = makeLazyScript("lazy_hung.js");
    let doneCalls = 0;
    lazyloader.loadScripts([script1], 0, () => doneCalls++);
    expect(doneCalls).toBe(0);

    await advanceTime(SCRIPT_LOAD_TIMEOUT_DELAY - 1);
    expect(doneCalls).toBe(0);
    expect.verifySteps([]);

    await advanceTime(1);
    expect(doneCalls).toBe(1);
    expect.verifySteps([
        `Lazy script did not settle within ${SCRIPT_LOAD_TIMEOUT_DELAY}ms,` +
            ` unblocking the page anyway: ${script1.src}`,
    ]);
});

test("a script that settles after the watchdog still runs, but is not reported twice", async () => {
    patchWithCleanup(console, {
        error: (message) => expect.step(String(message)),
    });
    const script1 = makeLazyScript("lazy_slow.js");
    const script2 = makeLazyScript("lazy_2.js");
    let doneCalls = 0;
    lazyloader.loadScripts([script1, script2], 0, () => doneCalls++);

    await advanceTime(SCRIPT_LOAD_TIMEOUT_DELAY + 1);
    expect(doneCalls).toBe(1);
    expect.verifySteps([
        `Lazy script did not settle within ${SCRIPT_LOAD_TIMEOUT_DELAY}ms,` +
            ` unblocking the page anyway: ${script1.src}`,
    ]);

    // the page is already unblocked, but the rest of the chain must still load
    script1.dispatchEvent(new Event("load"));
    expect(script2.src).toInclude("lazy_2.js");
    script2.dispatchEvent(new Event("load"));
    expect(doneCalls).toBe(1);

    await advanceTime(SCRIPT_LOAD_TIMEOUT_DELAY + 1);
    expect(doneCalls).toBe(1);
    expect.verifySteps([]);
});

test("empty chain resolves the singleton and clears the waiting state", async () => {
    document.body.classList.add("o_lazy_js_waiting");
    lazyloader.loadScripts([]);
    await lazyloader.allScriptsLoaded;
    expect(document.body).not.toHaveClass("o_lazy_js_waiting");
});

test("a stalled chain keeps its own watchdog when another chain completes", async () => {
    patchWithCleanup(console, {
        error: (message) => expect.step(String(message)),
    });
    const stalled = makeLazyScript("lazy_stalled.js");
    let stalledDone = 0;
    lazyloader.loadScripts([stalled], 0, () => stalledDone++);

    // a second, unrelated chain runs to completion while the first waits
    const quick = makeLazyScript("lazy_quick.js");
    let quickDone = 0;
    lazyloader.loadScripts([quick], 0, () => quickDone++);
    quick.dispatchEvent(new Event("load"));
    expect(quickDone).toBe(1);

    await advanceTime(SCRIPT_LOAD_TIMEOUT_DELAY + 1);
    expect.verifySteps([
        `Lazy script did not settle within ${SCRIPT_LOAD_TIMEOUT_DELAY}ms,` +
            ` unblocking the page anyway: ${stalled.src}`,
    ]);
    expect(stalledDone).toBe(1);
});
