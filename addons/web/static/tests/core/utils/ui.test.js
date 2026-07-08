// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import {
    getNextTabableElement,
    getTabableElements,
    isFocusable,
} from "@web/core/utils/dom/ui";

describe.current.tags("headless");

/**
 * Renders raw HTML into the test fixture and returns it.
 * @param {string} html
 * @returns {HTMLElement}
 */
function render(html) {
    const fixture = getFixture();
    fixture.innerHTML = html;
    return fixture;
}

test("getTabableElements excludes href-less anchors", () => {
    const fixture = render(`
        <a href="#one" id="with-href">with href</a>
        <a id="no-href">no href</a>
    `);
    const tabable = getTabableElements(fixture);
    expect(tabable.map((el) => el.id)).toEqual(["with-href"]);
});

test("getTabableElements excludes elements with tabIndex < 0", () => {
    // `tabindex="-2"` matches the `:not([tabindex=\"-1\"])` attribute guard but
    // is still non-tabable at the property level: it must be filtered out.
    const fixture = render(`
        <button id="b1">b1</button>
        <button id="b2" tabindex="-1">b2</button>
        <input id="i1" tabindex="-2"/>
    `);
    const tabable = getTabableElements(fixture);
    expect(tabable.map((el) => el.id)).toEqual(["b1"]);
});

test("getTabableElements orders positive tabIndex before 0", () => {
    const fixture = render(`
        <button id="zero">zero</button>
        <button id="two" tabindex="2">two</button>
        <button id="one" tabindex="1">one</button>
    `);
    const tabable = getTabableElements(fixture);
    expect(tabable.map((el) => el.id)).toEqual(["one", "two", "zero"]);
});

test("getNextTabableElement skips a href-less anchor (no dead spot)", () => {
    const fixture = render(`
        <button id="b1">b1</button>
        <a id="dead">not focusable</a>
        <button id="b2">b2</button>
    `);
    const first = /** @type {HTMLElement} */ (queryOne("#b1"));
    first.focus();
    expect(document.activeElement).toBe(first);
    // The href-less anchor must be skipped so navigation lands on a real
    // focusable element rather than a `.focus()`-noop dead spot.
    expect(getNextTabableElement(fixture)?.id).toBe("b2");
});

test("isFocusable returns false for a href-less anchor", () => {
    render(`
        <a href="#ok" id="ok">ok</a>
        <a id="ko">ko</a>
    `);
    expect(isFocusable(/** @type {HTMLElement} */ (queryOne("#ok")))).toBe(true);
    expect(isFocusable(/** @type {HTMLElement} */ (queryOne("#ko")))).toBe(false);
});
