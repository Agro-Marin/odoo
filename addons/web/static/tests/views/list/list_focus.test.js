// @ts-check

/**
 * Unit tests for list_focus.js — where focus goes inside a list, as pure
 * functions of a cell or a row.
 *
 * These are the parts of list keyboard handling that need no component: give
 * them a table and ask where focus should land. Until this file they had no
 * direct coverage at all — `useListKeyboardNavigation` (610 lines) and
 * `makeEditHandlers` (320) were reached only through the list view suite, which
 * is the one pair in the length budget with no unit tests behind it.
 */

import { after, describe, expect, test } from "@odoo/hoot";
import {
    containsActiveElement,
    findNextFocusableOnRow,
    findPreviousFocusableOnRow,
    focusAndSelect,
    getElementToFocus,
    togglesFocusInsideCell,
} from "@web/views/list/list_focus";

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

/**
 * @param {string} cellsHTML the <td> elements of a single row
 * @returns {HTMLTableRowElement}
 */
function makeRow(cellsHTML) {
    const table = document.createElement("table");
    table.innerHTML = `<tbody><tr>${cellsHTML}</tr></tbody>`;
    document.body.appendChild(table);
    after(() => table.remove());
    return /** @type {HTMLTableRowElement} */ (table.querySelector("tr"));
}

const dataCell = (inner) => `<td class="o_data_cell">${inner}</td>`;
const readonlyCell = (inner) =>
    `<td class="o_data_cell"><div class="o_readonly_modifier">${inner}</div></td>`;

describe("getElementToFocus", () => {
    test("returns the tabable element at the index", () => {
        const cell = makeCell(`<input class="a"/><input class="b"/>`);
        expect(getElementToFocus(cell, 0)).toBe(cell.querySelector(".a"));
        expect(getElementToFocus(cell, -1)).toBe(cell.querySelector(".b"));
    });

    test("falls back to the cell when it holds nothing tabable", () => {
        // Load-bearing: both row scans use `toFocus !== candidate` to mean
        // "this cell cannot take focus", which only works because of this.
        const cell = makeCell(`<span>plain</span>`);
        expect(getElementToFocus(cell, 0)).toBe(cell);
    });
});

describe("containsActiveElement", () => {
    test("true when focus is inside, false when it is the element itself", () => {
        const cell = makeCell(`<input class="a"/>`);
        /** @type {HTMLElement} */ (cell.querySelector(".a")).focus();
        expect(containsActiveElement(cell)).toBe(true);

        cell.tabIndex = -1;
        cell.focus();
        expect(containsActiveElement(cell)).toBe(false);
    });

    test("false when focus is elsewhere", () => {
        const cell = makeCell(`<input class="a"/>`);
        const other = makeCell(`<input class="b"/>`);
        /** @type {HTMLElement} */ (other.querySelector(".b")).focus();
        expect(containsActiveElement(cell)).toBe(false);
    });
});

describe("findNextFocusableOnRow", () => {
    test("returns the first focusable element after the given cell", () => {
        const row = makeRow(
            dataCell(`<input class="a"/>`) + dataCell(`<input class="b"/>`),
        );
        const first = /** @type {HTMLElement} */ (row.children[0]);
        expect(findNextFocusableOnRow(row, first)).toBe(row.querySelector(".b"));
    });

    test("skips cells that are not data cells", () => {
        const row = makeRow(
            dataCell(`<input class="a"/>`) +
                `<td class="o_list_record_selector"><input class="sel"/></td>` +
                dataCell(`<input class="b"/>`),
        );
        const first = /** @type {HTMLElement} */ (row.children[0]);
        expect(findNextFocusableOnRow(row, first)).toBe(row.querySelector(".b"));
    });

    test("skips readonly cells", () => {
        const row = makeRow(
            dataCell(`<input class="a"/>`) +
                readonlyCell(`<input class="ro"/>`) +
                dataCell(`<input class="b"/>`),
        );
        const first = /** @type {HTMLElement} */ (row.children[0]);
        expect(findNextFocusableOnRow(row, first)).toBe(row.querySelector(".b"));
    });

    test("skips data cells holding nothing tabable", () => {
        const row = makeRow(
            dataCell(`<input class="a"/>`) +
                dataCell(`<span>plain</span>`) +
                dataCell(`<input class="b"/>`),
        );
        const first = /** @type {HTMLElement} */ (row.children[0]);
        expect(findNextFocusableOnRow(row, first)).toBe(row.querySelector(".b"));
    });

    test("returns null at the end of the row", () => {
        const row = makeRow(dataCell(`<input class="a"/>`));
        const first = /** @type {HTMLElement} */ (row.children[0]);
        expect(findNextFocusableOnRow(row, first)).toBe(null);
    });
});

describe("findPreviousFocusableOnRow", () => {
    test("returns the last focusable element before the given cell", () => {
        const row = makeRow(
            dataCell(`<input class="a"/>`) + dataCell(`<input class="b"/>`),
        );
        const second = /** @type {HTMLElement} */ (row.children[1]);
        expect(findPreviousFocusableOnRow(row, second)).toBe(row.querySelector(".a"));
    });

    test("without a cell it scans back from past the end of the row", () => {
        // list_keyboard_edit calls it this way to enter a row from its right.
        const row = makeRow(
            dataCell(`<input class="a"/>`) + dataCell(`<input class="b"/>`),
        );
        expect(findPreviousFocusableOnRow(row)).toBe(row.querySelector(".b"));
    });

    test("takes the LAST tabable of the cell it lands on", () => {
        const row = makeRow(
            dataCell(`<input class="a"/><input class="a2"/>`) +
                dataCell(`<input class="b"/>`),
        );
        const second = /** @type {HTMLElement} */ (row.children[1]);
        expect(findPreviousFocusableOnRow(row, second)).toBe(row.querySelector(".a2"));
    });

    test("skips readonly and non-data cells, and returns null at the start", () => {
        const row = makeRow(
            `<td class="o_list_record_selector"><input class="sel"/></td>` +
                readonlyCell(`<input class="ro"/>`) +
                dataCell(`<input class="b"/>`),
        );
        const last = /** @type {HTMLElement} */ (row.children[2]);
        expect(findPreviousFocusableOnRow(row, last)).toBe(null);
    });
});

describe("focusAndSelect", () => {
    test("selects the whole value of a text input", () => {
        const cell = makeCell(`<input class="a" value="hello"/>`);
        const input = /** @type {HTMLInputElement} */ (cell.querySelector(".a"));
        focusAndSelect(input);
        expect(document.activeElement).toBe(input);
        expect(input.selectionStart).toBe(0);
        expect(input.selectionEnd).toBe(5);
    });

    test("leaves a caret the user already placed alone", () => {
        const cell = makeCell(`<input class="a" value="hello"/>`);
        const input = /** @type {HTMLInputElement} */ (cell.querySelector(".a"));
        input.focus();
        input.setSelectionRange(2, 4);
        focusAndSelect(input);
        expect(input.selectionStart).toBe(2);
        expect(input.selectionEnd).toBe(4);
    });

    test("focuses a non-text element without touching selection", () => {
        const cell = makeCell(`<button class="b">go</button>`);
        const button = /** @type {HTMLElement} */ (cell.querySelector(".b"));
        focusAndSelect(button);
        expect(document.activeElement).toBe(button);
    });

    test("is a no-op on null", () => {
        expect(() => focusAndSelect(null)).not.toThrow();
    });
});

describe("togglesFocusInsideCell", () => {
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
});
