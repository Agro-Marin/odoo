// @ts-check
/** @odoo-module native */

import { ModelEvent, SearchModelEvent } from "@web/core/events";
import { getTabableElements } from "@web/core/utils/dom/ui";
import { useBus } from "@web/core/utils/hooks";
import { applyFieldDirtyPayload } from "@web/fields/field_dirty_signal";

import {
    findNextFocusableOnRow,
    findPreviousFocusableOnRow,
    focusAndSelect,
    getElementToFocus,
    togglesFocusInsideCell,
} from "./list_focus.js";
import { makeEditHandlers } from "./list_keyboard_edit.js";

const MAX_VIRT_FOCUS_RETRIES = 20;

/** @typedef {"up" | "down" | "left" | "right"} Direction */

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
 * @param {Element} row
 * @param {"up" | "down"} direction
 * @returns {Element | null | undefined}
 */
function adjacentRow(row, direction) {
    if (direction === "up") {
        return (
            row.previousElementSibling ||
            row.parentElement.previousElementSibling?.lastElementChild
        );
    }
    return (
        row.nextElementSibling ||
        row.parentElement.nextElementSibling?.firstElementChild
    );
}

/**
 * @param {Element} row
 * @param {number} index
 * @param {{
 * direction: "up" | "down",
 * cellIsInGroupRow: boolean,
 * lastKnownIndex: number,
 * isHeaderRow: boolean,
 * }} params
 * @returns {{ cell: Element | undefined, lastKnownIndex: number,
 * rememberColumn?: number } | undefined}
 */
function verticalNeighbourCell(
    row,
    index,
    { direction, cellIsInGroupRow, lastKnownIndex, isHeaderRow },
) {
    const futureRow = adjacentRow(row, direction);
    if (!futureRow) {
        return undefined;
    }
    const addCell = [...futureRow.children].find((c) =>
        c.classList.contains("o_group_field_row_add"),
    );
    const nextIsGroup = futureRow.classList.contains("o_group_header");
    const rowTypeSwitched = cellIsInGroupRow !== nextIsGroup;
    const isGroupToGroup = cellIsInGroupRow && nextIsGroup;

    let targetIndex;
    if (rowTypeSwitched || isGroupToGroup) {
        targetIndex = lastKnownIndex || 0;
    } else {
        lastKnownIndex = index;
    }
    let rememberColumn;
    if (direction === "down" && isHeaderRow) {
        lastKnownIndex = index;
        rememberColumn = index;
    }
    const defaultIndex = cellIsInGroupRow ? targetIndex : 0;
    return {
        cell: addCell || futureRow.children[rowTypeSwitched ? defaultIndex : index],
        lastKnownIndex,
        rememberColumn,
    };
}

/**
 * @param {HTMLTableCellElement} cell
 * @param {1 | -1} step
 * @returns {Element | null}
 */
function adjacentGroupButton(cell, step) {
    const buttons = Array.from(cell.querySelectorAll(".o_group_buttons button"));
    const currentButton = document.activeElement.closest("button");
    return buttons[buttons.indexOf(currentButton) + step] || currentButton;
}

/**
 * @param {any} tableRef
 * @param {{ rowIndex: number, colIndex: number }} position
 * @param {"left" | "right"} [direction]
 * @returns {HTMLElement | null}
 */
function elementToFocusAtPosition(tableRef, { rowIndex, colIndex }, direction) {
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
 * @typedef {Pick<
 * import("./list_renderer").ListGridContext,
 * | "getColumns"
 * | "getProps"
 * | "getEnv"
 * | "getGridState"
 * | "onToggleGroup"
 * | "toggleRecordSelection"
 * | "onOpenRecord"
 * | "onDeleteRecord"
 * | "isInlineEditable"
 * | "expandCheckboxes"
 * | "getSel"
 * | "getVirtualization"
 * | "findFocusFutureCell"
 * | "setKeyboardNavigation"
 * > & import("./list_keyboard_edit").ListEditContext} ListKeyboardContext
 */

export class ListKeyboardNavigation {
    /** @type {{ column: any, record: any } | null} */
    lastEditedCell = null;
    /** @type {{ column: any, record: any, forward?: boolean } | null} */
    cellToFocus = null;
    lastIsDirty = false;
    /**
     * @type {{
     * cell: HTMLTableCellElement,
     * cellIsInGroupRow: boolean,
     * direction: string,
     * move: { el: HTMLElement } | { pending: true } | null,
     * } | null}
     */
    _latchedMove = null;
    _lastKnownIndex = 0;
    /**
     * @type {{ rowIndex: number, colIndex: number, recordId?: string, retries?: number, origin?: { cell: HTMLTableCellElement, cellIsInGroupRow: boolean, direction: "up" | "down" | "left" | "right" } } | null}
     */
    _pendingVirtFocus = null;

    /**
     * @param {any} tableRef
     * @param {ListKeyboardContext} ctx
     */
    constructor(tableRef, ctx) {
        this.tableRef = tableRef;
        this.ctx = ctx;
        // The members are a seam: a caller may capture one, replace it on the
        // instance and call the captured original unbound. Own bound methods
        // keep that contract; an assignment still replaces them.
        const proto = ListKeyboardNavigation.prototype;
        for (const name of Object.getOwnPropertyNames(proto)) {
            const descriptor = Object.getOwnPropertyDescriptor(proto, name);
            if (name !== "constructor" && typeof descriptor.value === "function") {
                this[name] = proto[name].bind(this);
            }
        }
    }

    get pendingVirtFocus() {
        return this._pendingVirtFocus;
    }

    /**
     * @param {HTMLElement} el
     */
    focus(el) {
        focusAndSelect(el);
    }

    /**
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {"up" | "down" | "left" | "right"} direction
     * @param {{ el: HTMLElement } | { pending: true } | null} [move]
     * @returns {HTMLElement | null}
     */
    _dispatchFutureCell(cell, cellIsInGroupRow, direction, move) {
        this._latchedMove =
            move === undefined ? null : { cell, cellIsInGroupRow, direction, move };
        try {
            return this.ctx.findFocusFutureCell(cell, cellIsInGroupRow, direction);
        } finally {
            this._latchedMove = null;
        }
    }

    /**
     * Land a focus that had to wait for virtualization to render its row.
     *
     * Two passes by design, and it is worth saying why rather than making
     * it one. The first finds the row (or counts a retry, if the scroll has
     * not painted it yet) and applies the focus; the *second* confirms the
     * focus stuck -- `element === document.activeElement` -- and only then
     * drops the pending state. Clearing on the first pass would trust a
     * focus() call nothing has yet confirmed.
     *
     * That confirmation is only sound because `toFocus` cannot diverge from
     * `element`: `_dispatchFutureCell` latches the move it was handed, and
     * `findFocusFutureCell` returns the latched element when the cell,
     * row-ness and direction all match. Without that latch the renderer's
     * hook could hand back a different cell, the equality would never hold,
     * and this would re-focus once per patch until MAX_VIRT_FOCUS_RETRIES.
     */
    resolvePendingVirtFocus() {
        const pending = this._pendingVirtFocus;
        if (!pending) {
            return;
        }
        let { rowIndex, colIndex } = pending;
        let recordStillExists = true;
        if (pending.recordId !== undefined) {
            const flat = this.ctx.getGridState?.()?.findRowByRecordId(pending.recordId);
            if (flat) {
                rowIndex = flat.globalIndex;
            } else {
                recordStillExists = false;
            }
        }
        if (!recordStillExists || (pending.retries || 0) >= MAX_VIRT_FOCUS_RETRIES) {
            this._pendingVirtFocus = null;
            return;
        }
        const element = elementToFocusAtPosition(this.tableRef, { rowIndex, colIndex });
        if (!element) {
            pending.retries = (pending.retries || 0) + 1;
            return;
        }
        const active = document.activeElement;
        if (element === active || element.contains(active)) {
            this._pendingVirtFocus = null;
            return;
        }
        if (
            active &&
            active !== document.body &&
            active.isConnected &&
            this.tableRef.el &&
            !this.tableRef.el.contains(active)
        ) {
            this._pendingVirtFocus = null;
            return;
        }
        const origin = pending.origin;
        const toFocus =
            origin && this.ctx.findFocusFutureCell
                ? this._dispatchFutureCell(
                      origin.cell,
                      origin.cellIsInGroupRow,
                      origin.direction,
                      { el: element },
                  )
                : element;
        if (toFocus) {
            this.focus(toFocus);
        }
        pending.retries = (pending.retries || 0) + 1;
    }

    clearPendingVirtFocus() {
        this._pendingVirtFocus = null;
    }

    /**
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {"up" | "down" | "left" | "right"} direction
     */
    setPendingVirtFocusOrigin(cell, cellIsInGroupRow, direction) {
        if (this._pendingVirtFocus) {
            this._pendingVirtFocus.origin = { cell, cellIsInGroupRow, direction };
        }
    }

    /**
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {"up" | "down" | "left" | "right"} direction
     * @returns {{ el: HTMLElement } | { pending: true } | null}
     */
    findFocusMove(cell, cellIsInGroupRow, direction) {
        const gridState = this.ctx.getGridState?.();
        const row = cell.parentElement;
        if (gridState && row.dataset.rowIndex !== undefined) {
            const move = this._findGridFocusMove(gridState, cell, row, direction);
            if (move) {
                return move;
            }
        }
        const children = /** @type {HTMLElement[]} */ ([...row.children]);
        const index = children.indexOf(/** @type {HTMLElement} */ (cell));
        let futureCell;
        if (gridState?.isRTL && (direction === "left" || direction === "right")) {
            direction = direction === "left" ? "right" : "left";
        }
        if (direction === "up" || direction === "down") {
            const vertical = verticalNeighbourCell(row, index, {
                direction,
                cellIsInGroupRow,
                lastKnownIndex: this._lastKnownIndex,
                isHeaderRow: this.tableRef.el.querySelector("thead tr") === row,
            });
            if (vertical) {
                futureCell = vertical.cell;
                this._lastKnownIndex = vertical.lastKnownIndex;
                if (vertical.rememberColumn !== undefined) {
                    this.ctx.getGridState?.()?.rememberColumn(vertical.rememberColumn);
                }
            }
        } else {
            const step = direction === "left" ? -1 : 1;
            futureCell = children[index + step];
            if (futureCell) {
                this._lastKnownIndex = index + step;
            }
        }
        const el =
            futureCell &&
            getElementToFocus(/** @type {HTMLTableCellElement} */ (futureCell));
        return el ? { el } : null;
    }

    /**
     * The move the grid state resolves, when the row carries a grid index:
     * an element when it is rendered, a pending marker when virtualization
     * still has to render it, null when the grid has no next cell.
     *
     * @param {import("./list_grid_state").ListGridState} gridState
     * @param {HTMLTableCellElement} cell
     * @param {HTMLElement} row
     * @param {"up" | "down" | "left" | "right"} direction
     * @returns {{ el: HTMLElement } | { pending: true } | null}
     */
    _findGridFocusMove(gridState, cell, row, direction) {
        const rowIndex = Number.parseInt(row.dataset.rowIndex, 10);
        const colIndex =
            cell.dataset.colIndex !== undefined
                ? Number.parseInt(cell.dataset.colIndex, 10)
                : [...row.children].indexOf(cell);
        const next = gridState.moveFocus(rowIndex, colIndex, direction);
        if (!next) {
            return null;
        }
        if (gridState.rowAt(next.rowIndex)?.type !== "group") {
            this._lastKnownIndex = next.colIndex;
        }
        const isHorizontal = direction === "left" || direction === "right";
        const indexDirection =
            isHorizontal && next.colIndex !== colIndex
                ? next.colIndex > colIndex
                    ? "right"
                    : "left"
                : undefined;
        const element = elementToFocusAtPosition(this.tableRef, next, indexDirection);
        if (element) {
            return { el: element };
        }
        const virt = this.ctx.getVirtualization?.();
        if (!virt?.isActive) {
            return null;
        }
        virt.ensureRowVisible(next.rowIndex);
        const flat = gridState.flatRows[next.rowIndex];
        this._pendingVirtFocus = {
            rowIndex: next.rowIndex,
            colIndex: next.colIndex,
            recordId:
                flat?.type === "record" && flat.record
                    ? String(flat.record.id)
                    : undefined,
        };
        return { pending: true };
    }

    /**
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {"up" | "down" | "left" | "right"} direction
     * @returns {HTMLElement | null}
     */
    findFocusFutureCell(cell, cellIsInGroupRow, direction) {
        const latched = this._latchedMove;
        const move =
            latched &&
            latched.cell === cell &&
            latched.cellIsInGroupRow === cellIsInGroupRow &&
            latched.direction === direction
                ? latched.move
                : this.findFocusMove(cell, cellIsInGroupRow, direction);
        return move && "el" in move ? move.el : null;
    }

    /**
     * @param {HTMLElement} row
     * @param {HTMLTableCellElement} [cell]
     * @returns {HTMLElement | null}
     */
    findNextFocusableOnRow(row, cell) {
        return findNextFocusableOnRow(row, cell);
    }

    /**
     * @param {HTMLElement} row
     * @param {HTMLTableCellElement} [cell]
     * @returns {HTMLElement | null}
     */
    findPreviousFocusableOnRow(row, cell) {
        return findPreviousFocusableOnRow(row, cell);
    }

    /**
     * @param {string} hotkey
     * @param {HTMLTableCellElement} cell
     * @returns {boolean}
     */
    toggleFocusInsideCell(hotkey, cell) {
        return togglesFocusInsideCell(hotkey, cell);
    }

    /**
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {"up"|"down"|"left"|"right"} direction
     * @returns {HTMLElement | true | null}
     */
    resolveArrowMove(cell, cellIsInGroupRow, direction) {
        const move = this.findFocusMove(cell, cellIsInGroupRow, direction);
        if (move && "pending" in move) {
            this.setPendingVirtFocusOrigin(cell, cellIsInGroupRow, direction);
            return true;
        }
        if (this.ctx.findFocusFutureCell) {
            return this._dispatchFutureCell(cell, cellIsInGroupRow, direction, move);
        }
        return move && "el" in move ? move.el : null;
    }

    /**
     * An arrow in read-only mode: on a group row, left and right fold and
     * unfold; on the x2many "add a line" cell they walk its links; otherwise
     * they move focus, which may already be handled (a pending virtual row)
     * or find nothing.
     *
     * @param {"up" | "down" | "left" | "right"} direction
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {object | null} group
     * @returns {{ handled: true } | { toFocus: Element | null }}
     */
    _readOnlyArrow(direction, cell, cellIsInGroupRow, group) {
        if (cellIsInGroupRow && direction === "left" && !group.isFolded) {
            this.ctx.onToggleGroup(group);
            return { handled: true };
        }
        if (cellIsInGroupRow && direction === "right" && group.isFolded) {
            this.ctx.onToggleGroup(group);
            return { handled: true };
        }
        if (
            (direction === "left" || direction === "right") &&
            cell.classList.contains("o_field_x2many_list_row_add")
        ) {
            const a = document.activeElement;
            return {
                toFocus:
                    direction === "left"
                        ? a.previousElementSibling
                        : a.nextElementSibling,
            };
        }
        const moved = this.resolveArrowMove(cell, cellIsInGroupRow, direction);
        if (moved === true) {
            return { handled: true };
        }
        if (!moved && direction === "up" && this.ctx.getEnv().searchModel) {
            this.ctx.getEnv().searchModel.trigger(SearchModelEvent.FOCUS_SEARCH);
            return { handled: true };
        }
        return { toFocus: moved };
    }

    /**
     * Enter in read-only mode: delete on the remove cell, the focused button
     * or the fold on a group row, edition on an editable or multi-edited
     * record, else the record itself.
     *
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {object | null} group
     * @param {object | null} record
     * @param {boolean} applyMultiEditBehavior
     * @returns {boolean}
     */
    _readOnlyEnter(cell, cellIsInGroupRow, group, record, applyMultiEditBehavior) {
        if (!group && !record) {
            return false;
        }
        if (cell.classList.contains("o_list_record_remove")) {
            this.ctx.onDeleteRecord(record);
            return true;
        }
        if (cellIsInGroupRow) {
            const button = document.activeElement.closest("button");
            if (button) {
                button.click();
            } else {
                this.ctx.onToggleGroup(group);
            }
            return true;
        }
        if (this.ctx.isInlineEditable(record) || applyMultiEditBehavior) {
            const column = this.ctx
                .getColumns()
                .find((c) => c.name === cell.getAttribute("name"));
            this.cellToFocus = { column, record };
            this.ctx.getProps().list.enterEditMode(record);
            return true;
        }
        if (!this.ctx.getProps().archInfo.noOpen) {
            this.ctx.onOpenRecord(record);
            return true;
        }
        return false;
    }

    /**
     * @param {string} hotkey
     * @param {HTMLTableCellElement} cell
     * @param {object | null} group
     * @param {object | null} record
     * @returns {boolean}
     */
    onCellKeydownReadOnlyMode(hotkey, cell, group, record) {
        const cellIsInGroupRow = Boolean(group && !record);
        const applyMultiEditBehavior =
            record?.selected && this.ctx.getProps().list.model.multiEdit;
        let toFocus;
        switch (hotkey) {
            case "arrowup":
            case "arrowdown":
            case "arrowleft":
            case "arrowright": {
                const direction = /** @type {"up" | "down" | "left" | "right"} */ (
                    hotkey.slice(5)
                );
                const arrow = this._readOnlyArrow(
                    direction,
                    cell,
                    cellIsInGroupRow,
                    group,
                );
                if ("handled" in arrow) {
                    return true;
                }
                toFocus = arrow.toFocus;
                break;
            }
            case "tab":
            case "shift+tab":
                if (cellIsInGroupRow) {
                    toFocus = adjacentGroupButton(cell, hotkey === "tab" ? 1 : -1);
                }
                break;
            case "shift+arrowdown":
            case "shift+arrowup": {
                const direction = hotkey === "shift+arrowdown" ? "down" : "up";
                if (this.ctx.expandCheckboxes(record, direction)) {
                    const moved = this.resolveArrowMove(
                        cell,
                        cellIsInGroupRow,
                        direction,
                    );
                    if (moved === true) {
                        return true;
                    }
                    toFocus = moved;
                }
                break;
            }
            case "shift+space":
                if (!record) {
                    return false;
                }
                this.ctx.toggleRecordSelection(record);
                toFocus = getElementToFocus(cell);
                break;
            case "shift":
                this.ctx.getSel().shiftKeyedRecord = record;
                break;
            case "enter":
                return this._readOnlyEnter(
                    cell,
                    cellIsInGroupRow,
                    group,
                    record,
                    applyMultiEditBehavior,
                );
            default:
                return false;
        }
        if (toFocus) {
            this.focus(/** @type {HTMLElement} */ (toFocus));
            return true;
        }
        return false;
    }
}

/**
 * @param {any} tableRef
 * @param {ListKeyboardContext} ctx
 * @returns {ListKeyboardNavigation & import("./list_keyboard_edit").ListEditHandlers}
 */
export function useListKeyboardNavigation(tableRef, ctx) {
    const nav = /** @type {any} */ (new ListKeyboardNavigation(tableRef, ctx));
    Object.assign(nav, makeEditHandlers(nav, tableRef, ctx));

    const dirtyOwners = new Set();
    useBus(
        ctx.getProps().list.model.bus,
        ModelEvent.FIELD_IS_DIRTY,
        (ev) =>
            (nav.lastIsDirty = applyFieldDirtyPayload(dirtyOwners, ev.detail).size > 0),
    );

    const env = ctx.getEnv();
    if (env.searchModel) {
        useBus(env.searchModel, SearchModelEvent.FOCUS_VIEW, () => {
            if (ctx.getProps().list.model.useSampleModel) {
                return;
            }
            const nextTh = tableRef.el?.querySelector("thead th");
            if (!nextTh) {
                return;
            }
            const toFocus = /** @type {HTMLElement} */ (
                getTabableElements(nextTh).at(0) || nextTh
            );
            nav.focus(toFocus);
            ctx.setKeyboardNavigation(true);
        });
    }

    return nav;
}
