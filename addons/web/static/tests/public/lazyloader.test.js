// @ts-check

import { after, describe, expect, getFixture, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { advanceTime } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import lazyloader, { stopWaitingLazy, waitLazy } from "@web/public/lazyloader";

describe.current.tags("headless");

const SCRIPT_LOAD_TIMEOUT_DELAY = 60000;

/**
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
    expect(script1.hasAttribute("defer")).toBe(false);
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

describe("waiting for the lazy JS", () => {
    /**
     * @param {string} html
     * @returns {HTMLElement}
     */
    function fixtureWith(html) {
        const fixture = /** @type {HTMLElement} */ (getFixture());
        fixture.innerHTML = html;
        return fixture;
    }

    function freeze() {
        waitLazy();
        after(() => stopWaitingLazy());
    }

    test("a click on a control anywhere under the root is frozen", async () => {
        fixtureWith(
            `<div id="wrapwrap"><button class="a"><span class="inner">x</span></button></div>`,
        );
        freeze();
        expect(document.body).toHaveClass("o_lazy_js_waiting");

        /** @type {string[]} */
        const seen = [];
        const button = queryOne(".a");
        button.addEventListener("click", () => seen.push("own-listener"));
        const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
        queryOne(".inner").dispatchEvent(ev);
        expect(seen).toEqual([]);
        expect(ev.defaultPrevented).toBe(true);
    });

    test("a control added after the freeze is left alone", async () => {
        fixtureWith(`<div id="wrapwrap"></div>`);
        freeze();
        queryOne("#wrapwrap").innerHTML = `<button class="late">x</button>`;
        /** @type {string[]} */
        const seen = [];
        const button = queryOne(".late");
        button.addEventListener("click", () => seen.push("own-listener"));
        button.dispatchEvent(
            new MouseEvent("click", { bubbles: true, cancelable: true }),
        );
        expect(seen).toEqual(["own-listener"]);
    });

    test("an opted-out control and a navigating link are left alone", async () => {
        fixtureWith(`
            <div id="wrapwrap">
                <button class="opted o_no_wait_lazy_js">x</button>
                <a class="nav" href="/somewhere">x</a>
                <a class="hash" href="#">x</a>
            </div>`);
        freeze();
        /** @type {string[]} */
        const seen = [];
        for (const sel of [".opted", ".nav", ".hash"]) {
            queryOne(sel).addEventListener("click", (/** @type {any} */ ev) => {
                ev.preventDefault();
                seen.push(sel);
            });
        }
        for (const sel of [".opted", ".nav", ".hash"]) {
            queryOne(sel).dispatchEvent(
                new MouseEvent("click", { bubbles: true, cancelable: true }),
            );
        }
        expect(seen).toEqual([".opted", ".nav"]);
    });

    test("each control keeps its own lock, so one hover cannot swallow another's click", async () => {
        fixtureWith(
            `<div id="wrapwrap"><button class="a">a</button><button class="b">b</button></div>`,
        );
        freeze();
        const a = queryOne(".a");
        const b = queryOne(".b");
        const first = new MouseEvent("click", { bubbles: true, cancelable: true });
        a.dispatchEvent(first);
        const second = new MouseEvent("click", { bubbles: true, cancelable: true });
        b.dispatchEvent(second);
        expect(first.defaultPrevented).toBe(true);
        expect(second.defaultPrevented).toBe(true);
    });

    test("a form submit is cancelled, unless the form opted out", async () => {
        fixtureWith(`
            <div id="wrapwrap"></div>
            <form class="outside"></form>
            <form class="opted o_no_wait_lazy_js"></form>`);
        freeze();
        /** @type {string[]} */
        const seen = [];
        for (const sel of ["form.outside", "form.opted"]) {
            const formEl = queryOne(sel);
            formEl.addEventListener("submit", (/** @type {any} */ ev) => {
                ev.preventDefault();
                seen.push(sel);
            });
            formEl.dispatchEvent(
                new Event("submit", { bubbles: true, cancelable: true }),
            );
        }
        expect(seen).toEqual(["form.opted"]);
    });

    test("stopWaitingLazy releases the page", async () => {
        fixtureWith(`<div id="wrapwrap"><button class="a">x</button></div>`);
        freeze();
        stopWaitingLazy();
        expect(document.body).not.toHaveClass("o_lazy_js_waiting");
        /** @type {string[]} */
        const seen = [];
        const button = queryOne(".a");
        button.addEventListener("click", () => seen.push("own-listener"));
        button.dispatchEvent(
            new MouseEvent("click", { bubbles: true, cancelable: true }),
        );
        expect(seen).toEqual(["own-listener"]);
    });
});
