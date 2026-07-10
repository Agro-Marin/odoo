// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import lazyloader from "@web/legacy/js/public/lazyloader";

// `lazyloader` (src/legacy/js/public/lazyloader.js) is production code shipped
// in `web.assets_frontend_minimal`: it blocks button/form events until the
// lazy `<script data-src>` chain has loaded (waitLazy), then replays them once
// the module-level `allScriptsLoaded` promise resolves (stopWaitingLazy).
//
// Those page singletons run at import time and settle within a tick on the
// test runner page (which has no `script[data-src]` node), so they cannot be
// re-armed from a test. The chain function is therefore exercised through its
// `onAllScriptsDone` seam — the very callback that production defaults to
// `allScriptsLoadedResolve`, whose only consumer is the one-line wiring
// `allScriptsLoaded.then(stopWaitingLazy)`: proving the callback fires proves
// the page gets unblocked.

describe.current.tags("headless");

// Timeout after which a script that fired neither "load" nor "error" stops
// blocking the page. Keep in sync with SCRIPT_LOAD_TIMEOUT_DELAY in
// `@web/legacy/js/public/lazyloader` (not exported: the production export
// surface is kept minimal on purpose).
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

    // First script started: data-src promoted to src, defer set.
    expect(script1.src).toInclude("lazy_1.js");
    expect(script1.hasAttribute("data-src")).toBe(false);
    expect(script1.getAttribute("defer")).toBe("defer");
    // Chain is sequential: the second script must not start yet.
    expect(script2.src).toBe("");
    expect(doneCalls).toBe(0);

    script1.dispatchEvent(new Event("load"));
    expect(script2.src).toInclude("lazy_2.js");
    expect(doneCalls).toBe(0);

    script2.dispatchEvent(new Event("load"));
    expect(doneCalls).toBe(1);

    // The watchdog was cleared on completion: advancing past the timeout
    // neither completes a second time nor logs anything.
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

    // Network error / 404: the script fires "error", never "load".
    script1.dispatchEvent(new Event("error"));
    expect.verifySteps([`Failed to load lazy script: ${script1.src}`]);

    // The chain moved on to the next script instead of stalling…
    expect(script2.src).toInclude("lazy_2.js");
    script2.dispatchEvent(new Event("load"));
    // …and still completed: in production this resolves allScriptsLoaded,
    // which runs stopWaitingLazy so clicks/submits stop being swallowed.
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

test("runner page singletons: allScriptsLoaded resolved and waiting state cleaned", async () => {
    // The import-time chain of this very page (no `script[data-src]` node)
    // resolved the singleton promise, which must have run stopWaitingLazy.
    await lazyloader.allScriptsLoaded;
    expect(document.body).not.toHaveClass("o_lazy_js_waiting");
});
