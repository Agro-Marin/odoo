// @ts-check
/** @odoo-module native */

import { getVisibleElements } from "@web/core/utils/dom/ui";

import { RISK } from "../interpreter/interpreter.js";

export const MAX_TARGETS = 99;

const TARGET_SELECTOR = [
    "button:not(:disabled)",
    "a[href]",
    "[role=button]",
    "[role=menuitem]",
    "[role=tab]",
    "[role=option]",
    "input:not([type=hidden]):not(:disabled)",
    "select:not(:disabled)",
    "textarea:not(:disabled)",
    ".o_data_row",
    ".o_kanban_record",
].join(", ");

const OWN_UI = ".o_voice_hud, .o_voice_numbers";

// a button carrying a server method, or one drawn as destructive, is pressed
// only after a confirmation, as a named button is
const COMMITTING = "button[type=object], button[type=action], .o_delete, .text-danger";

/**
 * @typedef {{ el: HTMLElement, label: string, risk: number }} Target
 */

/**
 * @param {HTMLElement} el
 * @returns {string}
 */
export function targetLabel(el) {
    const input = /** @type {HTMLInputElement} */ (el);
    const labelled = el.id
        ? el.ownerDocument.querySelector(`label[for="${CSS.escape(el.id)}"]`)
        : null;
    return (
        el.getAttribute("aria-label") ||
        el.getAttribute("title") ||
        el.dataset.tooltip ||
        labelled?.textContent ||
        el.textContent ||
        input.placeholder ||
        ""
    )
        .replace(/\s+/g, " ")
        .trim();
}

/**
 * What can be clicked in `root`, in reading order, the voice layer's own UI
 * left out.
 *
 * @param {Document | HTMLElement} root
 * @returns {Target[]}
 */
export function collectTargets(root) {
    return getVisibleElements(/** @type {HTMLElement} */ (root), TARGET_SELECTOR)
        .filter((el) => !el.closest(OWN_UI))
        .slice(0, MAX_TARGETS)
        .map((el) => ({
            el,
            label: targetLabel(el),
            risk: el.matches(COMMITTING) ? RISK.COMMIT : RISK.NAVIGATE,
        }));
}

/** @param {HTMLElement} el */
export function activateTarget(el) {
    if (el.matches("input, select, textarea")) {
        el.focus();
        return;
    }
    const cell = el.matches(".o_data_row") ? el.querySelector("td.o_data_cell") : null;
    /** @type {HTMLElement} */ (cell || el).click();
}
