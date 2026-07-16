// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_keyboard_nav - Keyboard navigation hook for arrow, tab, and enter key traversal across list view cells */

import { ModelEvent, SearchModelEvent } from "@web/core/events";
import { getTabableElements } from "@web/core/utils/dom/ui";
import { useBus } from "@web/core/utils/hooks";

import { makeEditHandlers } from "./list_keyboard_edit.js";

/**
 * Max onPatched cycles a virtualized-out focus latch is allowed to survive
 * unresolved. A virtualized scroll settles within a couple of patches, but a
 * heavy render (many reactive subscriptions) can split it across more; the
 * latch must outlive those so focus lands on the target row instead of
 * dropping to <body>. The cap bounds a pathological latch (target row that
 * never renders) so it cannot fire at an unrelated later patch and steal focus.
 */
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
    // Short rows (a group "Add a line" row has at most a selector cell plus
    // one colspan cell, none carrying data-col-index) clamp to their last
    // cell. Returning null for a RENDERED row made findFocusMove misdiagnose
    // it as virtualized-out: the viewport jumped to the row and focus waited
    // on a patch that could never resolve it — a focus trap at every group
    // boundary of a virtualized grouped list.
    const cell =
        row.querySelector(`[data-col-index="${colIndex}"]`) ||
        row.children[Math.min(colIndex, row.children.length - 1)];
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
        findFocusFutureCell,
    } = options;

    /**
     * Move already resolved by the calling handler, consumed by the hook's
     * ``findFocusFutureCell`` facade when the renderer override chain reaches
     * it, so a vertical arrow key does not compute ``findFocusMove`` twice.
     *
     * @type {{ cell: HTMLTableCellElement, direction: string, move: { el: HTMLElement } | { pending: true } | null } | null}
     */
    let latchedMove = null;

    /**
     * Resolve the target cell for an arrow move, dispatching through the
     * renderer-supplied (overridable) ``findFocusFutureCell`` when present so
     * downstream renderer subclasses observe/redirect the move; falls back to
     * the hook's internal facade otherwise. When the caller already computed
     * the move, pass it as ``move`` — the facade then consumes it instead of
     * recomputing (the latch only applies to the same cell/direction, so an
     * override calling ``super`` with different arguments still recomputes).
     *
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

    /** Index tracking for cross-row navigation between group and data rows. */
    let lastKnownIndex = 0;
    /**
     * Focus position to retry after virtualization scrolls the target into
     * view. Carries the grid indexes, the target record id (to re-resolve the
     * row index at resolution time if rows shifted meanwhile) and, for plain
     * arrow moves, the origin cell/direction so the resolution dispatches
     * through the renderer's overridable ``findFocusFutureCell``.
     *
     * @type {{ rowIndex: number, colIndex: number, recordId?: string, retries?: number, origin?: { cell: HTMLTableCellElement, cellIsInGroupRow: boolean, direction: "up" | "down" | "left" | "right" } } | null}
     */
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
         * Resolve focus for a pending virtualized-out position. Called from
         * onPatched. A single edge arrow move scrolls the target row into the
         * virtualization window, which can span several patches, and a patch
         * that lands *after* focus was applied can re-create the focused cell
         * node (dropping focus to <body>). The latch therefore stays sticky —
         * it survives across patches and re-applies focus whenever it was lost
         * — until focus rests on the target (settled) or the retry budget is
         * spent. It is never re-applied over another live element, so it cannot
         * steal focus the user moved elsewhere.
         */
        resolvePendingVirtFocus() {
            if (!pendingVirtFocus) {
                return;
            }
            const pending = pendingVirtFocus;
            let { rowIndex, colIndex } = pending;
            // Rows may have shifted between the arrow press and this patch
            // (insertion/removal while the scroll settled): re-resolve the row
            // index from the captured record id so focus lands on the intended
            // record, not whatever now sits at the latched index.
            let recordStillExists = true;
            if (pending.recordId !== undefined) {
                const flat = getGridState?.()?.findRowByRecordId(pending.recordId);
                if (flat) {
                    rowIndex = flat.globalIndex;
                } else {
                    recordStillExists = false;
                }
            }
            // Bound the latch's lifetime so a target that never renders (or a
            // record that was deleted) cannot leave a zombie latch that fires
            // at an unrelated later patch.
            if (
                !recordStillExists ||
                (pending.retries || 0) >= MAX_VIRT_FOCUS_RETRIES
            ) {
                pendingVirtFocus = null;
                return;
            }
            const element = focusAtPosition(tableRef, { rowIndex, colIndex });
            if (!element) {
                // The target row has not scrolled into the rendered window yet:
                // keep the latch so a later patch retries once it renders.
                pending.retries = (pending.retries || 0) + 1;
                return;
            }
            const active = document.activeElement;
            if (element === active || element.contains(active)) {
                // Focus already rests on the target: the move has settled.
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
                // Focus left the list entirely (the search bar, another widget,
                // a freshly opened part): the pending move is stale — abandon it
                // rather than yank focus back and steal it. Focus that is still
                // inside the table is either the origin cell we are moving away
                // from or a node a re-render is about to replace, so it does NOT
                // take this branch.
                pendingVirtFocus = null;
                return;
            }
            // Focus was lost to <body>/a detached node — a virtualization
            // re-render replaced the cell node mid-scroll. Re-apply it. A plain
            // arrow move dispatches the resolved cell through the renderer's
            // overridable findFocusFutureCell (with the resolution latched, so
            // no recompute) — subclasses that sync side state on arrow moves
            // (documents preview, account_accountant attachment preview)
            // observe virtualized-out moves like rendered ones.
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
            // Keep the latch (bounded): a subsequent re-render during the same
            // scroll can drop focus again; the next patch re-applies until it
            // sticks (cleared above once focus rests on the target).
            pending.retries = (pending.retries || 0) + 1;
        },

        /**
         * Drop a latched pending virtualized focus. The renderer calls this on
         * onPatched paths that must not resolve focus (active element owned by
         * another UI part, e.g. a dialog): without it the latch survives and
         * fires at a much later, unrelated patch with stale indexes — a focus
         * steal.
         */
        clearPendingVirtFocus() {
            pendingVirtFocus = null;
        },

        /**
         * Attach the origin of a pending virtualized-out arrow move so its
         * post-patch resolution dispatches through the renderer override
         * chain (see ``resolvePendingVirtFocus``). No-op when nothing is
         * pending.
         *
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
         * Discriminates three outcomes: `{ el }` (target cell rendered, focus it),
         * `{ pending: true }` (target row is virtualized out; scroll requested and
         * focus scheduled for the next patch via `resolvePendingVirtFocus` — callers
         * must treat the event as handled, not fall back to search-bar/scroll boundary
         * behavior), or `null` (grid boundary, no target row/cell in that direction).
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
                    // Group header rows force colIndex=0 (span all columns); skip
                    // updating lastKnownIndex for them so the legacy DOM-walking
                    // path still lands on the correct column at the grid boundary
                    // (e.g. thead).
                    if (gridState._flatRows[next.rowIndex]?.type !== "group") {
                        lastKnownIndex = next.colIndex;
                    }
                    const element = focusAtPosition(tableRef, next);
                    if (element) {
                        return { el: element };
                    }
                    // Row is virtualized out of DOM — scroll it into view
                    // and schedule focus for the next patch. Capture the
                    // target record id so the resolution can re-resolve the
                    // row index if rows shift before the patch fires.
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
         * Element-or-null facade over `findFocusMove`, kept because
         * `ListRenderer.findFocusFutureCell` delegates here and downstream
         * renderers (e.g. documents, account_accountant) override it expecting
         * an element or null. Cannot distinguish a boundary from a pending
         * virtualized focus — internal handlers use `findFocusMove` directly.
         * When the calling handler already resolved the move (vertical arrows
         * latch it through `dispatchFutureCell`), that resolution is consumed
         * here instead of computing `findFocusMove` a second time.
         *
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
            // With no `cell` (shift+tab cycle-to-last on a single-record list,
            // list_keyboard_edit.js), treat the position as past the end so the
            // scan covers every cell — mirroring findNextFocusableOnRow, where
            // slice(index + 1) with index === -1 already yields all cells.
            // Using indexOf(undefined) === -1 would make slice(0, -1) drop the
            // row's last (rightmost editable) cell.
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
                        // after the next patch (dispatched through the renderer
                        // override then — see resolvePendingVirtFocus). Consume
                        // the event so the search bar does not transiently
                        // steal focus.
                        self.setPendingVirtFocusOrigin(cell, cellIsInGroupRow, "up");
                        return true;
                    }
                    // When a renderer override is wired, resolve the concrete
                    // cell through it so subclasses observe the move; the
                    // already-computed move is latched so the chain's terminal
                    // facade does not recompute it.
                    toFocus = findFocusFutureCell
                        ? dispatchFutureCell(cell, cellIsInGroupRow, "up", move)
                        : move && move.el;
                    if (!toFocus && getEnv().searchModel) {
                        getEnv().searchModel.trigger(SearchModelEvent.FOCUS_SEARCH);
                        return true;
                    }
                    break;
                }
                case "arrowdown": {
                    const move = self.findFocusMove(cell, cellIsInGroupRow, "down");
                    if (move && "pending" in move) {
                        // Focus is scheduled for the next patch (dispatched
                        // through the renderer override then) — consume the
                        // event to prevent the default browser scroll.
                        self.setPendingVirtFocusOrigin(cell, cellIsInGroupRow, "down");
                        return true;
                    }
                    // Dispatch through the renderer override when wired (see
                    // arrowup) so subclass findFocusFutureCell participates,
                    // passing the already-computed move to avoid recompute.
                    toFocus = findFocusFutureCell
                        ? dispatchFutureCell(cell, cellIsInGroupRow, "down", move)
                        : move && move.el;
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
                    // Group-header (and any non-record) rows have no record to
                    // toggle. Without this guard onToggleRecordSelection(null)
                    // -> toggleRangeSelection(null) dereferences records[-1] and
                    // throws a TypeError.
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

    // Edit handlers (from list_keyboard_edit.js) close over `self` and call nav
    // methods (focus, findNextFocusableOnRow, etc.) via late binding.
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
