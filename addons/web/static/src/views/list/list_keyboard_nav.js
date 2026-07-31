// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_keyboard_nav */

import { ModelEvent, SearchModelEvent } from "@web/core/events";
import { getTabableElements } from "@web/core/utils/dom/ui";
import { useBus } from "@web/core/utils/hooks";
import { applyFieldDirtyPayload } from "@web/fields/field_dirty_signal";

import { makeEditHandlers } from "./list_keyboard_edit.js";

const MAX_VIRT_FOCUS_RETRIES = 20;

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
 * @param {Element} row
 * @param {number} colIndex
 * @param {"left" | "right"} [direction]
 * @returns {Element | null}
 */
function nearestCellOnRow(row, colIndex, direction) {
    if (direction !== "left" && direction !== "right") {
        return null;
    }
    const cells = [...row.querySelectorAll("[data-col-index]")].map((cell) => ({
        cell,
        index: Number.parseInt(
            /** @type {string} */ (cell.getAttribute("data-col-index")),
            10,
        ),
    }));
    const reachable = cells.filter((c) =>
        direction === "left" ? c.index <= colIndex : c.index >= colIndex,
    );
    if (!reachable.length) {
        return null;
    }
    return reachable.reduce((best, c) =>
        Math.abs(c.index - colIndex) < Math.abs(best.index - colIndex) ? c : best,
    ).cell;
}

/**
 * @param {any} tableRef
 * @param {{ rowIndex: number, colIndex: number }} position
 * @param {"left" | "right"} [direction]
 * @returns {HTMLElement | null}
 */
function focusAtPosition(tableRef, { rowIndex, colIndex }, direction) {
    const row = tableRef.el.querySelector(`[data-row-index="${rowIndex}"]`);
    if (!row) {
        return null;
    }
    const cell =
        row.querySelector(`[data-col-index="${colIndex}"]`) ||
        nearestCellOnRow(row, colIndex, direction) ||
        row.children[Math.min(colIndex, row.children.length - 1)];
    if (!cell) {
        return null;
    }
    return getElementToFocus(cell);
}

/**
 * @param {any} tableRef
 * @param {object} options
 * @param {() => import("./list_renderer").Column[]} options.getColumns
 * @param {() => import("./list_renderer").ListRendererProps} options.getProps
 * @param {() => object} options.getEnv
 * @param {() => import("./list_grid_state").ListGridState | undefined} [options.getGridState]
 * @param {() => object | null} [options.getEditedRecord]
 * @param {(cell: HTMLTableCellElement, cellIsInGroupRow: boolean, direction: "up" | "down" | "left" | "right") => HTMLElement | null} [options.findFocusFutureCell]
 * @param {(group: object) => void} options.onToggleGroup
 * @param {(record: object) => void} options.onToggleRecordSelection
 * @param {(params?: object) => void} [options.onAdd]
 * @param {(record: object) => void} options.onOpenRecord
 * @param {(record: object) => void} options.onDeleteRecord
 * @param {(record: object, group?: object) => any} [options.onEditNextRecord]
 * @param {(record: object) => boolean} options.isInlineEditable
 * @param {(column: any, record: object) => boolean} [options.isCellReadonly]
 * @param {(record: object, direction: string) => boolean} options.expandCheckboxes
 * @param {() => object} [options.getSel]
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
        findFocusFutureCell,
    } = options;

    /**
     * @type {{ cell: HTMLTableCellElement, direction: string, move: { el: HTMLElement } | { pending: true } | null } | null}
     */
    let latchedMove = null;

    /**
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {"up" | "down" | "left" | "right"} direction
     * @param {{ el: HTMLElement } | { pending: true } | null} [move]
     * @returns {HTMLElement | null}
     */
    const dispatchFutureCell = (cell, cellIsInGroupRow, direction, move) => {
        latchedMove = move === undefined ? null : { cell, direction, move };
        try {
            return (findFocusFutureCell || self.findFocusFutureCell)(
                cell,
                cellIsInGroupRow,
                direction,
            );
        } finally {
            latchedMove = null;
        }
    };

    let lastKnownIndex = 0;
    /**
     * @type {{ rowIndex: number, colIndex: number, recordId?: string, retries?: number, origin?: { cell: HTMLTableCellElement, cellIsInGroupRow: boolean, direction: "up" | "down" | "left" | "right" } } | null}
     */
    let pendingVirtFocus = null;

    const self = {
        lastEditedCell: null,
        cellToFocus: null,
        lastIsDirty: false,
        get pendingVirtFocus() {
            return pendingVirtFocus;
        },
        resolvePendingVirtFocus() {
            if (!pendingVirtFocus) {
                return;
            }
            const pending = pendingVirtFocus;
            let { rowIndex, colIndex } = pending;
            let recordStillExists = true;
            if (pending.recordId !== undefined) {
                const flat = getGridState?.()?.findRowByRecordId(pending.recordId);
                if (flat) {
                    rowIndex = flat.globalIndex;
                } else {
                    recordStillExists = false;
                }
            }
            if (
                !recordStillExists ||
                (pending.retries || 0) >= MAX_VIRT_FOCUS_RETRIES
            ) {
                pendingVirtFocus = null;
                return;
            }
            const element = focusAtPosition(tableRef, { rowIndex, colIndex });
            if (!element) {
                pending.retries = (pending.retries || 0) + 1;
                return;
            }
            const active = document.activeElement;
            if (element === active || element.contains(active)) {
                pendingVirtFocus = null;
                return;
            }
            if (
                active &&
                active !== document.body &&
                active.isConnected &&
                tableRef.el &&
                !tableRef.el.contains(active)
            ) {
                pendingVirtFocus = null;
                return;
            }
            const origin = pending.origin;
            const toFocus =
                origin && findFocusFutureCell
                    ? dispatchFutureCell(
                          origin.cell,
                          origin.cellIsInGroupRow,
                          origin.direction,
                          { el: element },
                      )
                    : element;
            if (toFocus) {
                self.focus(toFocus);
            }
            pending.retries = (pending.retries || 0) + 1;
        },

        clearPendingVirtFocus() {
            pendingVirtFocus = null;
        },

        /**
         * @param {HTMLTableCellElement} cell
         * @param {boolean} cellIsInGroupRow
         * @param {"up" | "down" | "left" | "right"} direction
         */
        setPendingVirtFocusOrigin(cell, cellIsInGroupRow, direction) {
            if (pendingVirtFocus) {
                pendingVirtFocus.origin = { cell, cellIsInGroupRow, direction };
            }
        },

        /**
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
         * @param {HTMLTableCellElement} cell
         * @param {boolean} cellIsInGroupRow
         * @param {"up" | "down" | "left" | "right"} direction
         * @returns {{ el: HTMLElement } | { pending: true } | null}
         */
        findFocusMove(cell, cellIsInGroupRow, direction) {
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
                    if (gridState.rowAt(next.rowIndex)?.type !== "group") {
                        lastKnownIndex = next.colIndex;
                    }
                    const isHorizontal = direction === "left" || direction === "right";
                    const indexDirection =
                        isHorizontal && next.colIndex !== colIndex
                            ? next.colIndex > colIndex
                                ? "right"
                                : "left"
                            : undefined;
                    const element = focusAtPosition(tableRef, next, indexDirection);
                    if (element) {
                        return { el: element };
                    }
                    const virt = getVirtualization?.();
                    if (virt?.isActive) {
                        virt.ensureRowVisible(next.rowIndex);
                        const flat = gridState.flatRows[next.rowIndex];
                        pendingVirtFocus = {
                            rowIndex: next.rowIndex,
                            colIndex: next.colIndex,
                            recordId:
                                flat?.type === "record" && flat.record
                                    ? String(flat.record.id)
                                    : undefined,
                        };
                        return { pending: true };
                    }
                }
            }

            const children = /** @type {HTMLElement[]} */ ([...row.children]);
            const index = children.indexOf(/** @type {HTMLElement} */ (cell));
            let futureCell;
            let targetIndex;
            if (gridState?.isRTL && (direction === "left" || direction === "right")) {
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
                            const gs = getGridState?.();
                            if (gs) {
                                gs.rememberColumn(index);
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
         * @param {HTMLTableCellElement} cell
         * @param {boolean} cellIsInGroupRow
         * @param {"up" | "down" | "left" | "right"} direction
         * @returns {HTMLElement | null}
         */
        findFocusFutureCell(cell, cellIsInGroupRow, direction) {
            const move =
                latchedMove &&
                latchedMove.cell === cell &&
                latchedMove.direction === direction
                    ? latchedMove.move
                    : self.findFocusMove(cell, cellIsInGroupRow, direction);
            return move && "el" in move ? move.el : null;
        },

        /**
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
         * @param {HTMLElement} row
         * @param {HTMLTableCellElement} [cell]
         * @returns {HTMLElement | null}
         */
        findPreviousFocusableOnRow(row, cell) {
            const children = /** @type {HTMLElement[]} */ ([...row.children]);
            const index = cell ? children.indexOf(cell) : children.length;
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
         * @param {string} hotkey
         * @param {HTMLTableCellElement} cell
         * @returns {boolean}
         */
        toggleFocusInsideCell(hotkey, cell) {
            return togglesFocusInsideCell(hotkey, cell);
        },

        /**
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
                        self.setPendingVirtFocusOrigin(cell, cellIsInGroupRow, "up");
                        return true;
                    }
                    toFocus = findFocusFutureCell
                        ? dispatchFutureCell(cell, cellIsInGroupRow, "up", move)
                        : move && "el" in move
                          ? move.el
                          : null;
                    if (!toFocus && getEnv().searchModel) {
                        getEnv().searchModel.trigger(SearchModelEvent.FOCUS_SEARCH);
                        return true;
                    }
                    break;
                }
                case "arrowdown": {
                    const move = self.findFocusMove(cell, cellIsInGroupRow, "down");
                    if (move && "pending" in move) {
                        self.setPendingVirtFocusOrigin(cell, cellIsInGroupRow, "down");
                        return true;
                    }
                    toFocus = findFocusFutureCell
                        ? dispatchFutureCell(cell, cellIsInGroupRow, "down", move)
                        : move && "el" in move
                          ? move.el
                          : null;
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
                        toFocus = dispatchFutureCell(cell, cellIsInGroupRow, "left");
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
                        toFocus = dispatchFutureCell(cell, cellIsInGroupRow, "right");
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
                        toFocus = move && "el" in move ? move.el : null;
                    }
                    break;
                }
                case "shift+arrowup": {
                    if (expandCheckboxes(record, "up")) {
                        const move = self.findFocusMove(cell, cellIsInGroupRow, "up");
                        if (move && "pending" in move) {
                            return true;
                        }
                        toFocus = move && "el" in move ? move.el : null;
                    }
                    break;
                }
                case "shift+space":
                    if (!record) {
                        return false;
                    }
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

    Object.assign(self, makeEditHandlers(self, tableRef, options));

    const dirtyOwners = new Set();
    useBus(
        getProps().list.model.bus,
        ModelEvent.FIELD_IS_DIRTY,
        (ev) =>
            (self.lastIsDirty =
                applyFieldDirtyPayload(dirtyOwners, ev.detail).size > 0),
    );

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
