// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_focus */

import { getTabableElements } from "@web/core/utils/dom/ui";

/**
 * Where focus goes inside a list, as pure functions of a cell or a row.
 *
 * A leaf on purpose. `list_keyboard_nav` and `list_keyboard_edit` both need
 * these, and reaching them through the navigator object is what made the two
 * modules import each other — the only import cycle in `web`. None of them
 * reads the navigator's state, so neither module has to be involved.
 *
 * It is also the part of list keyboard handling that can be tested without
 * mounting anything: give it a table and ask where focus should land.
 */

/**
 * @param {HTMLTableCellElement} cell
 * @param {number} [index]
 * @returns {HTMLElement}
 */
export function getElementToFocus(cell, index) {
    return /** @type {HTMLElement} */ (getTabableElements(cell).at(index) || cell);
}

/**
 * @param {HTMLElement} parent
 * @returns {boolean}
 */
export function containsActiveElement(parent) {
    const { activeElement } = document;
    return parent !== activeElement && parent.contains(activeElement);
}

/**
 * True when tab/shift+tab should move within the cell rather than leave it.
 *
 * @param {string} hotkey
 * @param {HTMLTableCellElement} cell
 * @returns {boolean}
 */
export function togglesFocusInsideCell(hotkey, cell) {
    if (!["tab", "shift+tab"].includes(hotkey) || !containsActiveElement(cell)) {
        return false;
    }
    const focusableEls = getTabableElements(cell).filter(
        (el) =>
            el === document.activeElement ||
            ["INPUT", "BUTTON", "TEXTAREA"].includes(el.tagName),
    );
    const index = focusableEls.indexOf(
        /** @type {HTMLElement} */ (document.activeElement),
    );
    if (index === -1) {
        return false;
    }
    return hotkey === "tab" ? index < focusableEls.length - 1 : index > 0;
}

/**
 * A cell is skipped when it is not a data cell, or when its content is
 * readonly: neither can take focus.
 *
 * @param {HTMLElement} candidate
 * @returns {boolean}
 */
function canTakeFocus(candidate) {
    if (!candidate.classList.contains("o_data_cell")) {
        return false;
    }
    return !candidate.firstElementChild?.classList.contains("o_readonly_modifier");
}

/**
 * @param {HTMLElement} row
 * @param {HTMLElement} [cell] the cell to start from; omit to start past the end
 * @returns {HTMLElement | null}
 */
export function findNextFocusableOnRow(row, cell) {
    const children = /** @type {HTMLElement[]} */ ([...row.children]);
    const index = children.indexOf(/** @type {HTMLElement} */ (cell));
    for (const candidate of children.slice(index + 1)) {
        if (!canTakeFocus(candidate)) {
            continue;
        }
        const toFocus = getElementToFocus(
            /** @type {HTMLTableCellElement} */ (candidate),
            0,
        );
        if (toFocus !== candidate) {
            return toFocus;
        }
    }
    return null;
}

/**
 * @param {HTMLElement} row
 * @param {HTMLElement} [cell] the cell to start from; omit to start past the end
 * @returns {HTMLElement | null}
 */
export function findPreviousFocusableOnRow(row, cell) {
    const children = /** @type {HTMLElement[]} */ ([...row.children]);
    const index = cell ? children.indexOf(cell) : children.length;
    for (const candidate of children.slice(0, index).reverse()) {
        if (!canTakeFocus(candidate)) {
            continue;
        }
        const toFocus = getElementToFocus(
            /** @type {HTMLTableCellElement} */ (candidate),
            -1,
        );
        if (toFocus !== candidate) {
            return toFocus;
        }
    }
    return null;
}

/**
 * Focuses `el`, selecting its content when it is a text entry the user is
 * expected to overtype. Only selects when there is no selection already, so
 * that a caret the user placed deliberately survives.
 *
 * @param {HTMLElement | null | undefined} el
 * @returns {void}
 */
export function focusAndSelect(el) {
    if (!el) {
        return;
    }
    el.focus();
    const inputEl = /** @type {HTMLInputElement} */ (el);
    if (
        ["text", "search", "url", "tel", "password", "textarea"].includes(
            inputEl.type,
        ) &&
        inputEl.selectionStart === inputEl.selectionEnd
    ) {
        inputEl.selectionStart = 0;
        inputEl.selectionEnd = inputEl.value.length;
    }
}
