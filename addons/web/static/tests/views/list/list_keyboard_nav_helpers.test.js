// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import { togglesFocusInsideCell } from "@web/views/list/list_keyboard_nav";

describe.current.tags("headless");

/**
 * Build a detached-but-rendered <td> so getTabableElements' visibility filter
 * sees real layout.
 *
 * @param {string} innerHTML
 * @returns {HTMLTableCellElement}
 */
function makeCell(innerHTML) {
    const table = document.createElement("table");
    table.innerHTML = `<tbody><tr><td>${innerHTML}</td></tr></tbody>`;
    document.body.appendChild(table);
    after(() => table.remove());
    return /** @type {HTMLTableCellElement} */ (table.querySelector("td"));
}

test("no toggle when the cell owns a single tabable element", () => {
    const cell = makeCell(`<input class="a"/>`);
    /** @type {HTMLElement} */ (cell.querySelector(".a")).focus();
    expect(togglesFocusInsideCell("tab", cell)).toBe(false);
    expect(togglesFocusInsideCell("shift+tab", cell)).toBe(false);
});

test("toggle between two tabable elements of the same cell", () => {
    const cell = makeCell(`<input class="a"/><input class="b"/>`);
    /** @type {HTMLElement} */ (cell.querySelector(".a")).focus();
    expect(togglesFocusInsideCell("tab", cell)).toBe(true);
    expect(togglesFocusInsideCell("shift+tab", cell)).toBe(false);

    /** @type {HTMLElement} */ (cell.querySelector(".b")).focus();
    expect(togglesFocusInsideCell("tab", cell)).toBe(false);
    expect(togglesFocusInsideCell("shift+tab", cell)).toBe(true);
});

test("a focused contenteditable is not in the tab ring: no toggle either way", () => {
    // An html field renders a focusable contenteditable that getTabableElements
    // never matches; the cell's toolbar button IS in the ring. Tab must reach
    // the list's own cell navigation instead of being reported as intra-cell.
    const cell = makeCell(
        `<div class="ed" contenteditable="true">x</div><button class="b">b</button>`,
    );
    /** @type {HTMLElement} */ (cell.querySelector(".ed")).focus();
    expect(document.activeElement).toBe(cell.querySelector(".ed"));
    expect(togglesFocusInsideCell("tab", cell)).toBe(false);
    expect(togglesFocusInsideCell("shift+tab", cell)).toBe(false);
});

test("a focused tabindex=-1 element is not in the tab ring: no toggle either way", () => {
    const cell = makeCell(`<input class="a" tabindex="-1"/><input class="b"/>`);
    /** @type {HTMLElement} */ (cell.querySelector(".a")).focus();
    expect(togglesFocusInsideCell("tab", cell)).toBe(false);
    expect(togglesFocusInsideCell("shift+tab", cell)).toBe(false);
});

test("non-tab hotkeys and focus outside the cell never toggle", () => {
    const cell = makeCell(`<input class="a"/><input class="b"/>`);
    /** @type {HTMLElement} */ (cell.querySelector(".a")).focus();
    expect(togglesFocusInsideCell("arrowdown", cell)).toBe(false);

    /** @type {HTMLElement} */ (document.activeElement).blur();
    expect(togglesFocusInsideCell("tab", cell)).toBe(false);
});
