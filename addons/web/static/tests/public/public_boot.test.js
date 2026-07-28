// @ts-check

import { after, describe, expect, getFixture, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { setupGlobalPageBehaviors } from "@web/public/public_boot";

describe.current.tags("headless");

/**
 * Installs the page-global behaviours for the duration of one test.
 *
 * A submit event has to reach `document.body`, where the behaviours delegate
 * from, but must not travel on to `window`, where the test framework forwards
 * form submissions to a (mocked) fetch. Stopping it at the document leaves the
 * event un-prevented, which is the state the delegation is meant to act on.
 *
 * @param {string} html
 */
function setupPage(html) {
    getFixture().innerHTML = html;
    const stopAtDocument = (/** @type {Event} */ ev) => ev.stopPropagation();
    document.addEventListener("submit", stopAtDocument);
    after(() => document.removeEventListener("submit", stopAtDocument));
    after(setupGlobalPageBehaviors());
}

/**
 * @param {string} [selector]
 * @returns {Event} the dispatched event, so that a test can cancel it later
 */
function submit(selector = "form") {
    const ev = new Event("submit", { bubbles: true, cancelable: true });
    queryOne(selector).dispatchEvent(ev);
    return ev;
}

describe("submit progress indicator", () => {
    test("marks the submit buttons of a js_website_submit_form", () => {
        setupPage(`
            <form class="js_website_submit_form">
                <button type="submit">Send</button>
            </form>`);
        submit();
        expect("button").toHaveProperty("disabled", true);
        expect("button .fa-circle-notch").toHaveCount(1);
    });

    test("leaves other forms alone", () => {
        setupPage(`
            <form>
                <button type="submit">Send</button>
            </form>`);
        submit();
        expect("button").toHaveProperty("disabled", false);
        expect("button .fa-circle-notch").toHaveCount(0);
    });

    test("is not applied when the submit was already cancelled", () => {
        setupPage(`
            <form class="js_website_submit_form">
                <button type="submit"><i class="fa fa-check"></i> Send</button>
            </form>`);
        // a handler on the form runs before the delegated one on the body
        queryOne("form").addEventListener("submit", (ev) => ev.preventDefault());
        submit();
        expect("button").toHaveProperty("disabled", false);
        expect("button .fa-circle-notch").toHaveCount(0);
        // the button's own icon must survive
        expect("button .fa-check").toHaveCount(1);
        expect("button i").toHaveCount(1);
    });

    test("is undone when the submit is cancelled afterwards", () => {
        setupPage(`
            <form class="js_website_submit_form">
                <button type="submit"><i class="fa fa-check"></i> Send</button>
            </form>`);
        const ev = submit();
        expect("button").toHaveProperty("disabled", true);
        expect("button .fa-circle-notch").toHaveCount(1);
        // a listener registered after the delegated one cancels the submit
        ev.preventDefault();
        expect("button").toHaveProperty("disabled", false);
        expect("button .fa-circle-notch").toHaveCount(0);
        expect("button .fa-check").toHaveCount(1);
    });

    test("a button that was already disabled stays disabled once undone", () => {
        setupPage(`
            <form class="js_website_submit_form">
                <button type="submit" disabled="disabled">Send</button>
            </form>`);
        submit().preventDefault();
        expect("button").toHaveProperty("disabled", true);
        expect("button .fa-circle-notch").toHaveCount(0);
    });

    test("an anchor submitter keeps the properties it never had", () => {
        setupPage(`
            <form class="js_website_submit_form">
                <a href="#" class="a-submit">Send</a>
            </form>`);
        const ev = submit();
        expect("a.a-submit .fa-circle-notch").toHaveCount(1);
        ev.preventDefault();
        expect("a.a-submit .fa-circle-notch").toHaveCount(0);
        expect(queryOne("a.a-submit").textContent.trim()).toBe("Send");
    });
});

describe("disable on click", () => {
    test("adds the disabled class", async () => {
        setupPage(`<button class="js_disable_on_click">Go</button>`);
        await click("button");
        expect("button").toHaveClass("disabled");
    });
});

describe("background images", () => {
    test("a src holding a quote cannot inject declarations", () => {
        setupPage(
            `<div class="o_image" data-mimetype="image/png"
                  data-src="/a.png&quot;); background-color: rgb(1, 2, 3); --x: (&quot;"></div>`,
        );
        const el = /** @type {HTMLElement} */ (queryOne(".o_image"));
        expect(el.style.backgroundColor).toBe("");
        expect(el.style.backgroundImage).toInclude("a.png");
    });

    test("a plain src is applied", () => {
        setupPage(
            `<div class="o_image" data-mimetype="image/png" data-src="/web/image/1"></div>`,
        );
        expect(
            /** @type {HTMLElement} */ (queryOne(".o_image")).style.backgroundImage,
        ).toBe('url("/web/image/1")');
    });

    test("a non-raster mimetype is left alone", () => {
        setupPage(
            `<div class="o_image" data-mimetype="image/svg+xml" data-src="/a.svg"></div>`,
        );
        expect(
            /** @type {HTMLElement} */ (queryOne(".o_image")).style.backgroundImage,
        ).toBe("");
    });
});
