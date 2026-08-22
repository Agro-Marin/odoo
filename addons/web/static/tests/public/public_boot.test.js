// @ts-check

import { after, describe, expect, getFixture, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { setupGlobalPageBehaviors } from "@web/public/public_boot";

describe.current.tags("headless");

/**
 * @param {string} html
 */
function setupPage(html) {
    /** @type {HTMLElement} */ (getFixture()).innerHTML = html;
    const stopAtDocument = (/** @type {Event} */ ev) => ev.stopPropagation();
    document.addEventListener("submit", stopAtDocument);
    after(() => document.removeEventListener("submit", stopAtDocument));
    after(setupGlobalPageBehaviors());
}

/**
 * @param {string} [selector]
 * @returns {Event}
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
        queryOne("form").addEventListener("submit", (ev) => ev.preventDefault());
        submit();
        expect("button").toHaveProperty("disabled", false);
        expect("button .fa-circle-notch").toHaveCount(0);
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

    test("an anchor with the old a-submit class is left alone", () => {
        setupPage(`
            <form class="js_website_submit_form">
                <a href="#" class="a-submit">Send</a>
            </form>`);
        submit();
        expect("a.a-submit .fa-circle-notch").toHaveCount(0);
        expect(queryOne("a.a-submit").textContent?.trim()).toBe("Send");
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

describe("scrollTop hash", () => {
    /**
     * @param {string} hash
     * @returns {Array<[number, number]>}
     */
    function scrollsFor(hash) {
        /** @type {Array<[number, number]>} */
        const scrolls = [];
        patchWithCleanup(browser.location, { hash });
        patchWithCleanup(window, {
            scrollTo: /** @type {typeof window.scrollTo} */ (
                (/** @type {any} */ x, /** @type {any} */ y) => {
                    scrolls.push([x, y]);
                }
            ),
        });
        setupPage("");
        return scrolls;
    }

    test("scrolls to the offset the hash carries", () => {
        expect(scrollsFor("#scrollTop=1200")).toEqual([[0, 1200]]);
    });

    test("reads the offset out of a longer hash", () => {
        expect(scrollsFor("#part=2&scrollTop=40")).toEqual([[0, 40]]);
    });

    test("does not scroll without the hash", () => {
        expect(scrollsFor("#somewhere-else")).toEqual([]);
    });

    test("ignores a non-numeric offset rather than scrolling to NaN", () => {
        expect(scrollsFor("#scrollTop=abc")).toEqual([]);
    });
});
