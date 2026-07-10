// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_keyboard_nav - Keyboard navigation hook for arrow, tab, and enter key traversal across list view cells */

import { ModelEvent, SearchModelEvent } from "@web/core/events";
import { getTabableElements } from "@web/core/utils/dom/ui";
import { useBus } from "@web/core/utils/hooks";

import { makeEditHandlers } from "./list_keyboard_edit.js";
/**
 * @param {HTMLTableCellElement} cell
 * @param {number} [index]
 */
export function getElementToFocus(cell, index) {
    return /** @type {HTMLElement} */ (getTabableElements(cell).at(index) || cell);
}

/**
 * @param {HTMLElement} parent
 */
export function containsActiveElement(parent) {
    const { activeElement } = document;
    return parent !== activeElement && parent.contains(activeElement);
}

/**
 * Resolve a grid index pair to a focusable DOM element.
 *
 * @param {any} tableRef
 * @param {{ rowIndex: number, colIndex: number }} position
 * @returns {HTMLElement | null}
 */
function focusAtPosition(tableRef, { rowIndex, colIndex }) {
    const row = tableRef.el.querySelector(`[data-row-index="${rowIndex}"]`);
    if (!row) {
        return null;
    }
    const cell =
        row.querySelector(`[data-col-index="${colIndex}"]`) || row.children[colIndex];
    if (!cell) {
        return null;
    }
    return getElementToFocus(cell);
}

/**
 * Hook encapsulating the keyboard navigation subsystem for the list view.
 *
 * Handles arrow/tab/enter/escape navigation in both read-only and edit modes,
 * including multi-edit, grouped lists, and focus management across rows and cells.
 *
 * @param {any} tableRef - ref to the <table> element
 * @param {object} options
 * @param {() => import("./list_renderer").Column[]} options.getColumns
 * @param {() => import("./list_renderer").ListRendererProps} options.getProps
 * @param {() => object} options.getEnv
 * @param {() => import("./list_grid_state").ListGridState | undefined} [options.getGridState]
 * @param {() => object | null} [options.getEditedRecord]
 * @param {(group: object) => void} options.onToggleGroup
 * @param {(record: object) => void} options.onToggleRecordSelection
 * @param {(params?: object) => void} [options.onAdd]
 * @param {(record: object) => void} options.onOpenRecord
 * @param {(record: object) => void} options.onDeleteRecord
 * @param {(record: object, group?: object) => any} [options.onEditNextRecord]
 * @param {(record: object) => boolean} options.isInlineEditable
 * @param {(column: any, record: object) => boolean} [options.isCellReadonly]
 * @param {(record: object, direction: string) => boolean} options.expandCheckboxes
 * @param {() => object} [options.getSel] - selection hook
 * @param {() => boolean} [options.getCanCreate]
 * @param {() => boolean} [options.getDisplayRowCreates]
 * @param {() => any[]} [options.getControls]
 * @param {() => import("./list_virtualization").ListVirtualization | undefined} [options.getVirtualization]
 * @returns {any}
 */
export function useListKeyboardNavigation(tableRef, options) {
    const {
        getColumns,
        getProps,
        getEnv,
        getGridState,
        onToggleGroup,
        onToggleRecordSelection,
        onOpenRecord,
        onDeleteRecord,
        isInlineEditable,
        expandCheckboxes,
        getSel,
        getVirtualization,
    } = options;

    /** Index tracking for cross-row navigation between group and data rows. */
    let lastKnownIndex = 0;
    /** Focus position to retry after virtualization scrolls the target into view. */
    let pendingVirtFocus = null;

    const self = {
        /** The cell that was last edited — used to restore focus after patch. */
        lastEditedCell: null,
        /** Cell to focus after the next patch (set before enterEditMode). */
        cellToFocus: null,
        /** Whether the last field change marked the record as dirty. */
        lastIsDirty: false,
        /** Pending virtualization focus — set when a row was virtualized out. */
        get pendingVirtFocus() {
            return pendingVirtFocus;
        },
        /**
         * Retry focus for a pending virtualized-out position.
         * Call from onPatched after virtualization has scrolled the row into view.
         */
        resolvePendingVirtFocus() {
            if (!pendingVirtFocus) {
                return;
            }
            const pos = pendingVirtFocus;
            pendingVirtFocus = null;
            const element = focusAtPosition(tableRef, pos);
            if (element) {
                self.focus(element);
            }
        },

        /**
         * Focus an element, selecting its text content if applicable.
         *
         * @param {HTMLElement} el
         */
        focus(el) {
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
        },

        /**
         * Navigate from a cell to a neighbouring cell in the given direction (read-only mode).
         *
         * Uses index-based navigation via ListGridState when data-row-index attributes are
         * present; falls back to DOM-walking for rows without index attributes (legacy path).
         *
         * The result discriminates the three possible outcomes so that callers
         * can tell "no target at all" apart from "target exists but is not
         * rendered yet":
         *
         * - `{ el }` — the target cell is rendered: focus this element.
         * - `{ pending: true }` — the target row exists but is virtualized out
         *   of the DOM. Virtualization has been asked to scroll it into view
         *   and focus is scheduled for the next patch (see
         *   `resolvePendingVirtFocus`). Callers must treat the event as
         *   handled and must NOT fall back to boundary behaviors (focusing
         *   the search bar, default browser scroll).
         * - `null` — grid boundary: no target row/cell in that direction.
         *
         * @param {HTMLTableCellElement} cell
         * @param {boolean} cellIsInGroupRow
         * @param {"up" | "down" | "left" | "right"} direction
         * @returns {{ el: HTMLElement } | { pending: true } | null}
         */
        findFocusMove(cell, cellIsInGroupRow, direction) {
            // Index-based path: use ListGridState when data attributes are present
            const gridState = getGridState?.();
            const row = cell.parentElement;
            if (gridState && row.dataset.rowIndex !== undefined) {
                const rowIndex = Number.parseInt(row.dataset.rowIndex, 10);
                const colIndex =
                    cell.dataset.colIndex !== undefined
                        ? Number.parseInt(cell.dataset.colIndex, 10)
                        : [...row.children].indexOf(cell);
                const next = gridState.moveFocus(rowIndex, colIndex, direction);
                if (next) {
                    // Group header rows always force colIndex=0 (they span all
                    // columns). Skip updating lastKnownIndex for them so the
                    // legacy DOM-walking path still lands on the correct column
                    // when navigation reaches the grid boundary (e.g. thead).
                    if (gridState._flatRows[next.rowIndex]?.type !== "group") {
                        lastKnownIndex = next.colIndex;
                    }
                    const element = focusAtPosition(tableRef, next);
                    if (element) {
                        return { el: element };
                    }
                    // Row is virtualized out of DOM — scroll it into view
                    // and schedule focus for the next patch.
                    const virt = getVirtualization?.();
                    if (virt?.isActive) {
                        virt.ensureRowVisible(next.rowIndex);
                        pendingVirtFocus = next;
                        return { pending: true };
                    }
                }
                // At grid boundary: fall through to legacy path so it can
                // handle transitions between tbody and thead.
            }

            // Legacy DOM-walking path (unchanged, except the RTL swap below)
            const children = /** @type {HTMLElement[]} */ ([...row.children]);
            const index = children.indexOf(/** @type {HTMLElement} */ (cell));
            let futureCell;
            let targetIndex;
            // DOM order is logical order: in RTL layouts the horizontal
            // arrows must be swapped here too, or ArrowRight moves visually
            // right on data rows (grid path swaps it) but visually left on
            // header rows (this path).
            if (gridState?._isRTL && (direction === "left" || direction === "right")) {
                direction = direction === "left" ? "right" : "left";
            }
            switch (direction) {
                case "up": {
                    let futureRow = row.previousElementSibling;
                    futureRow =
                        futureRow ||
                        row.parentElement.previousElementSibling?.lastElementChild;
                    if (futureRow) {
                        const addCell = [...futureRow.children].find((c) =>
                            c.classList.contains("o_group_field_row_add"),
                        );
                        const nextIsGroup =
                            futureRow.classList.contains("o_group_header");
                        const rowTypeSwitched = cellIsInGroupRow !== nextIsGroup;
                        const isGroupToGroup = cellIsInGroupRow && nextIsGroup;
                        if (rowTypeSwitched || isGroupToGroup) {
                            targetIndex = lastKnownIndex || 0;
                        } else {
                            lastKnownIndex = index;
                        }
                        const defaultIndex = cellIsInGroupRow ? targetIndex : 0;
                        futureCell =
                            addCell ||
                            (futureRow &&
                                futureRow.children[
                                    rowTypeSwitched ? defaultIndex : index
                                ]);
                    }
                    break;
                }
                case "down": {
                    let futureRow = row.nextElementSibling;
                    futureRow =
                        futureRow ||
                        row.parentElement.nextElementSibling?.firstElementChild;
                    if (futureRow) {
                        const addCell = [...futureRow.children].find((c) =>
                            c.classList.contains("o_group_field_row_add"),
                        );
                        const nextIsGroup =
                            futureRow.classList.contains("o_group_header");
                        const rowTypeSwitched = cellIsInGroupRow !== nextIsGroup;
                        const isGroupToGroup = cellIsInGroupRow && nextIsGroup;
                        const headerRow = tableRef.el.querySelector("thead tr");
                        if (rowTypeSwitched || isGroupToGroup) {
                            targetIndex = lastKnownIndex || 0;
                        } else {
                            lastKnownIndex = index;
                        }
                        const defaultIndex = cellIsInGroupRow ? targetIndex : 0;
                        if (headerRow === row) {
                            lastKnownIndex = index;
                            // Bridge column info to the grid state so that
                            // subsequent index-based group→record navigation
                            // restores the header column position.
                            const gs = getGridState?.();
                            if (gs) {
                                gs._lastColIndex = index;
                            }
                        }
                        futureCell =
                            addCell ||
                            (futureRow &&
                                futureRow.children[
                                    rowTypeSwitched ? defaultIndex : index
                                ]);
                    }
                    break;
                }
                case "left": {
                    futureCell = children[index - 1];
                    if (futureCell) {
                        lastKnownIndex = index - 1;
                    }
                    break;
                }
                case "right": {
                    futureCell = children[index + 1];
                    if (futureCell) {
                        lastKnownIndex = index + 1;
                    }
                    break;
                }
            }
            const el =
                futureCell &&
                getElementToFocus(/** @type {HTMLTableCellElement} */ (futureCell));
            return el ? { el } : null;
        },

        /**
         * Element-or-null facade over `findFocusMove`.
         *
         * Kept because `ListRenderer.findFocusFutureCell` delegates here and
         * downstream renderers override that method expecting an element (or
         * null) — see e.g. the documents and account_accountant list
         * renderers. This facade cannot distinguish a grid boundary from a
         * pending virtualized focus; internal arrow handlers use
         * `findFocusMove` instead.
         *
         * @param {HTMLTableCellElement} cell
         * @param {boolean} cellIsInGroupRow
         * @param {"up" | "down" | "left" | "right"} direction
         * @returns {HTMLElement | null}
         */
        findFocusFutureCell(cell, cellIsInGroupRow, direction) {
            const move = self.findFocusMove(cell, cellIsInGroupRow, direction);
            return move && "el" in move ? move.el : null;
        },

        /**
         * Find the next focusable cell to the right on the same row.
         *
         * @param {HTMLElement} row
         * @param {HTMLTableCellElement} [cell]
         * @returns {HTMLElement | null}
         */
        findNextFocusableOnRow(row, cell) {
            const children = /** @type {HTMLElement[]} */ ([...row.children]);
            const index = children.indexOf(/** @type {HTMLElement} */ (cell));
            const nextCells = children.slice(index + 1);
            for (const c of nextCells) {
                if (!c.classList.contains("o_data_cell")) {
                    continue;
                }
                if (
                    c.firstElementChild &&
                    c.firstElementChild.classList.contains("o_readonly_modifier")
                ) {
                    continue;
                }
                const toFocus = getElementToFocus(
                    /** @type {HTMLTableCellElement} */ (c),
                    0,
                );
                if (toFocus !== c) {
                    return toFocus;
                }
            }
            return null;
        },

        /**
         * Find the previous focusable cell to the left on the same row.
         *
         * @param {HTMLElement} row
         * @param {HTMLTableCellElement} [cell]
         * @returns {HTMLElement | null}
         */
        findPreviousFocusableOnRow(row, cell) {
            const children = /** @type {HTMLElement[]} */ ([...row.children]);
            const index = children.indexOf(/** @type {HTMLElement} */ (cell));
            const previousCells = children.slice(0, index);
            for (const c of previousCells.reverse()) {
                if (!c.classList.contains("o_data_cell")) {
                    continue;
                }
                if (
                    c.firstElementChild &&
                    c.firstElementChild.classList.contains("o_readonly_modifier")
                ) {
                    continue;
                }
                const toFocus = getElementToFocus(
                    /** @type {HTMLTableCellElement} */ (c),
                    -1,
                );
                if (toFocus !== c) {
                    return toFocus;
                }
            }
            return null;
        },

        /**
         * Returns true if the focus was toggled inside the same cell (tab between inputs).
         *
         * @param {string} hotkey
         * @param {HTMLTableCellElement} cell
         * @returns {boolean}
         */
        toggleFocusInsideCell(hotkey, cell) {
            if (
                !["tab", "shift+tab"].includes(hotkey) ||
                !containsActiveElement(cell)
            ) {
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
            return (
                (hotkey === "tab" && index < focusableEls.length - 1) ||
                (hotkey === "shift+tab" && index > 0)
            );
        },

        /**
         * Handle keyboard in read-only mode (navigation, selection, group toggle).
         *
         * @param {string} hotkey
         * @param {HTMLTableCellElement} cell
         * @param {object | null} group
         * @param {object | null} record
         * @returns {boolean}
         */
        onCellKeydownReadOnlyMode(hotkey, cell, group, record) {
            const cellIsInGroupRow = Boolean(group && !record);
            const props = getProps();
            const applyMultiEditBehavior =
                record?.selected && props.list.model.multiEdit;
            let toFocus;
            switch (hotkey) {
                case "arrowup": {
                    const move = self.findFocusMove(cell, cellIsInGroupRow, "up");
                    if (move && "pending" in move) {
                        // The target row is virtualized out: focus lands on it
                        // after the next patch. Consume the event so the
                        // search bar does not transiently steal focus.
                        return true;
                    }
                    toFocus = move && move.el;
                    if (!toFocus && getEnv().searchModel) {
                        getEnv().searchModel.trigger(SearchModelEvent.FOCUS_SEARCH);
                        return true;
                    }
                    break;
                }
                case "arrowdown": {
                    const move = self.findFocusMove(cell, cellIsInGroupRow, "down");
                    if (move && "pending" in move) {
                        // Focus is scheduled for the next patch — consume the
                        // event to prevent the default browser scroll.
                        return true;
                    }
                    toFocus = move && move.el;
                    break;
                }
                case "arrowleft":
                    if (cellIsInGroupRow && !group.isFolded) {
                        onToggleGroup(group);
                        return true;
                    }
                    if (cell.classList.contains("o_field_x2many_list_row_add")) {
                        const a = document.activeElement;
                        toFocus = a.previousElementSibling;
                    } else {
                        toFocus = self.findFocusFutureCell(
                            cell,
                            cellIsInGroupRow,
                            "left",
                        );
                    }
                    break;
                case "arrowright":
                    if (cellIsInGroupRow && group.isFolded) {
                        onToggleGroup(group);
                        return true;
                    }
                    if (cell.classList.contains("o_field_x2many_list_row_add")) {
                        const a = document.activeElement;
                        toFocus = a.nextElementSibling;
                    } else {
                        toFocus = self.findFocusFutureCell(
                            cell,
                            cellIsInGroupRow,
                            "right",
                        );
                    }
                    break;
                case "tab":
                    if (cellIsInGroupRow) {
                        const buttons = Array.from(
                            cell.querySelectorAll(".o_group_buttons button"),
                        );
                        const currentButton = document.activeElement.closest("button");
                        const index = buttons.indexOf(currentButton);
                        toFocus = buttons[index + 1] || currentButton;
                    }
                    break;
                case "shift+tab":
                    if (cellIsInGroupRow) {
                        const buttons = Array.from(
                            cell.querySelectorAll(".o_group_buttons button"),
                        );
                        const currentButton = document.activeElement.closest("button");
                        const index = buttons.indexOf(currentButton);
                        toFocus = buttons[index - 1] || currentButton;
                    }
                    break;
                case "shift+arrowdown": {
                    if (expandCheckboxes(record, "down")) {
                        const move = self.findFocusMove(cell, cellIsInGroupRow, "down");
                        if (move && "pending" in move) {
                            return true;
                        }
                        toFocus = move && move.el;
                    }
                    break;
                }
                case "shift+arrowup": {
                    if (expandCheckboxes(record, "up")) {
                        const move = self.findFocusMove(cell, cellIsInGroupRow, "up");
                        if (move && "pending" in move) {
                            return true;
                        }
                        toFocus = move && move.el;
                    }
                    break;
                }
                case "shift+space":
                    onToggleRecordSelection(record);
                    toFocus = getElementToFocus(cell);
                    break;
                case "shift":
                    getSel().shiftKeyedRecord = record;
                    break;
                case "enter":
                    if (!group && !record) {
                        return false;
                    }
                    if (cell.classList.contains("o_list_record_remove")) {
                        onDeleteRecord(record);
                        return true;
                    }
                    if (cellIsInGroupRow) {
                        const button = document.activeElement.closest("button");
                        if (button) {
                            button.click();
                        } else {
                            onToggleGroup(group);
                        }
                        return true;
                    }
                    if (isInlineEditable(record) || applyMultiEditBehavior) {
                        const columns = getColumns();
                        const column = columns.find(
                            (c) => c.name === cell.getAttribute("name"),
                        );
                        self.cellToFocus = { column, record };
                        props.list.enterEditMode(record);
                        return true;
                    }
                    if (!props.archInfo.noOpen) {
                        onOpenRecord(record);
                        return true;
                    }
                    break;
                default:
                    return false;
            }

            if (toFocus) {
                self.focus(/** @type {HTMLElement} */ (toFocus));
                return true;
            }
            return false;
        },
    };

    // Compose edit-mode handlers onto self (from list_keyboard_edit.js).
    // Edit handlers close over `self` and call nav methods (focus,
    // findNextFocusableOnRow, etc.) at invocation time via late binding.
    Object.assign(self, makeEditHandlers(self, tableRef, options));

    // Track field dirtiness for edit-mode navigation decisions.
    useBus(
        getProps().list.model.bus,
        ModelEvent.FIELD_IS_DIRTY,
        (ev) => (self.lastIsDirty = ev.detail),
    );

    // Handle "focus-view" from the search model (e.g., after breadcrumb navigation).
    const env = getEnv();
    if (env.searchModel) {
        useBus(env.searchModel, SearchModelEvent.FOCUS_VIEW, () => {
            if (getProps().list.model.useSampleModel) {
                return;
            }
            const nextTh = tableRef.el.querySelector("thead th");
            const toFocus = /** @type {HTMLElement} */ (
                getTabableElements(nextTh).at(0) || nextTh
            );
            self.focus(toFocus);
            tableRef.el.querySelector("tbody").classList.add("o_keyboard_navigation");
        });
    }

    return self;
}
