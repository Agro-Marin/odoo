// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_virtualization - Row virtualization hook rendering only visible rows plus buffer for large list views */

/**
 * Row virtualization hook for the list view. Wraps `useVirtualGrid` and
 * `ListGridState` to render only visible rows + buffer. Activates
 * automatically once flat row count exceeds threshold and drag-and-drop is
 * not active; below threshold, zero overhead — all rows render normally.
 *
 * Usage in ListRenderer.setup():
 *
 *     this.virt = useListVirtualization({
 *         rootRef: this.rootRef,
 *         getGridState: () => this.gridState,
 *         getNbCols: () => this.nbCols,
 *         canResequence: () => this.canResequenceRows,
 *         getEditedRecord: () => this.editedRecord,
 *     });
 *
 *     // In onWillRender, after gridState.rebuild():
 *     this.virt.refresh();
 */

import { onMounted, onPatched } from "@odoo/owl";
import { useVirtualGrid } from "@web/core/utils/virtual_grid";
const DEFAULT_ROW_HEIGHT = 41; // px — standard Odoo list row
const DEFAULT_GROUP_ROW_HEIGHT = 37; // px — group header row
const DEFAULT_THRESHOLD = 100;
const DEFAULT_BUFFER_COEF = 0.5;

/**
 * @typedef {import("./list_grid_state").FlatRow} FlatRow
 *
 * @typedef ListVirtualizationOptions
 * @property {any} rootRef - ref to .o_list_renderer
 * @property {() => import("./list_grid_state").ListGridState} getGridState
 * @property {() => number} getNbCols - total column count (for spacer colspan)
 * @property {() => boolean} canResequence - whether drag reorder is active
 * @property {() => object | null} getEditedRecord - currently edited record
 * @property {number} [threshold] - min flat rows to activate virtualization
 * @property {number} [bufferCoef] - buffer coefficient for useVirtualGrid
 */

/**
 * @typedef ListVirtualization
 * @property {boolean} isActive - whether virtualization is currently engaged
 * @property {FlatRow[]} visibleFlatRows - slice of flatRows to render
 * @property {number} topSpacerHeight - CSS px for top spacer <tr>
 * @property {number} bottomSpacerHeight - CSS px for bottom spacer <tr>
 * @property {(rowIndex: number) => void} ensureRowVisible - scroll to make a row visible
 * @property {() => void} refresh - recompute visible range (call in onWillRender)
 */

/**
 * Hook providing row virtualization for the list view.
 *
 * @param {ListVirtualizationOptions} options
 * @returns {ListVirtualization}
 */
export function useListVirtualization({
    rootRef,
    getGridState,
    getNbCols,
    canResequence,
    getEditedRecord,
    threshold = DEFAULT_THRESHOLD,
    bufferCoef = DEFAULT_BUFFER_COEF,
}) {
    // Measured row heights (set once from the real DOM on first patched)
    let measuredRowHeight = 0;
    let measuredGroupRowHeight = 0;

    // Current state
    let active = false;
    /** @type {FlatRow[]} */
    let visible = [];
    let topHeight = 0;
    let bottomHeight = 0;
    /** @type {number[]} */
    let heights = [];
    /** @type {number[]} */
    let cumHeights = [];

    const virtualGrid = useVirtualGrid({
        scrollableRef: rootRef,
        bufferCoef,
    });

    /**
     * Measure actual row height from the first rendered data row.
     * Called once after first mount/patch with data rows in the DOM.
     */
    function measureRowHeights() {
        const el = rootRef.el;
        if (!el) {
            return;
        }
        // The measured heights are only consumed while virtualization is
        // active. Skip the getBoundingClientRect reads (which force a synchronous
        // reflow — costly after every inline-edit patch) when it is inactive:
        // a small x2many list inside a form paid two forced reflows per patch
        // for numbers it never used, defeating the column-width hook's
        // reflow-free discipline. On first activation `refresh()` falls back to
        // the DEFAULT_* constants for one frame, then this measures.
        if (!active) {
            return;
        }
        // Re-measure on every patch, not just once: density (compact/comfortable)
        // and browser zoom change row height at runtime, and a stale measurement
        // desynced the spacer math and ensureRowVisible. Negligible cost next to
        // the virtualization's own layout reads.
        const dataRow = el.querySelector(".o_data_row");
        if (dataRow) {
            const rowHeight =
                dataRow.getBoundingClientRect().height || DEFAULT_ROW_HEIGHT;
            if (rowHeight !== measuredRowHeight) {
                measuredRowHeight = rowHeight;
            }
        }
        const groupRow = el.querySelector(".o_group_header");
        if (groupRow) {
            const groupHeight =
                groupRow.getBoundingClientRect().height || DEFAULT_GROUP_ROW_HEIGHT;
            if (groupHeight !== measuredGroupRowHeight) {
                measuredGroupRowHeight = groupHeight;
            }
        }
    }

    onMounted(measureRowHeights);
    onPatched(measureRowHeights);

    const result = {
        get isActive() {
            return active;
        },
        get visibleFlatRows() {
            return visible;
        },
        get topSpacerHeight() {
            return topHeight;
        },
        get bottomSpacerHeight() {
            return bottomHeight;
        },

        /**
         * Scroll the container to make a given flat row index visible.
         *
         * @param {number} rowIndex - globalIndex in the flat rows array
         */
        ensureRowVisible(rowIndex) {
            if (!active || !rootRef.el) {
                return;
            }
            if (rowIndex < 0 || rowIndex >= cumHeights.length) {
                return;
            }
            const targetTop = rowIndex > 0 ? cumHeights[rowIndex - 1] : 0;
            const containerHeight = rootRef.el.clientHeight;
            const scrollTo = Math.max(0, targetTop - containerHeight / 2); // center in viewport
            rootRef.el.scrollTop = scrollTo;
        },

        /**
         * Recompute the visible range from current grid state.
         * Must be called in onWillRender, after gridState.rebuild().
         */
        refresh() {
            const gridState = getGridState();
            const flatRows = gridState.flatRows;
            const rowCount = flatRows.length;

            if (rowCount <= threshold || canResequence()) {
                active = false;
                visible = [];
                topHeight = 0;
                bottomHeight = 0;
                return;
            }

            active = true;

            const rowH = measuredRowHeight || DEFAULT_ROW_HEIGHT;
            const groupH = measuredGroupRowHeight || DEFAULT_GROUP_ROW_HEIGHT;

            // Rebuild the per-row heights, but only push them into the virtual
            // grid when they actually changed. refresh() runs on EVERY render —
            // including every throttled scroll frame — and setRowsHeights()
            // deletes the grid's cached rowsIndexes and recomputes them from
            // index 0 (prevStartIndex === undefined), discarding the
            // incremental, prevStartIndex-optimized window the scroll listener
            // already computed for this same frame. Calling it unconditionally
            // turned each scroll frame's O(window) index search into an O(n)
            // rescan from the top plus a redundant O(n) cumHeights rebuild. When
            // the heights are unchanged we leave the grid's fresh indexes in
            // place and reuse the cached cumHeights. (`heights` is non-empty iff
            // setRowsHeights was already called with it, so reading rowsIndexes
            // and cumHeights below is safe on the unchanged path.)
            const newHeights = new Array(rowCount);
            let heightsChanged = rowCount !== heights.length;
            for (let i = 0; i < rowCount; i++) {
                const h = flatRows[i].type === "group" ? groupH : rowH;
                newHeights[i] = h;
                if (!heightsChanged && heights[i] !== h) {
                    heightsChanged = true;
                }
            }

            if (heightsChanged) {
                heights = newHeights;
                virtualGrid.setRowsHeights(heights);
                // Cumulative heights, used for spacer sizing and ensureRowVisible
                cumHeights = new Array(rowCount);
                let acc = 0;
                for (let i = 0; i < rowCount; i++) {
                    acc += heights[i];
                    cumHeights[i] = acc;
                }
            }

            const indexes = virtualGrid.rowsIndexes;
            if (!indexes || /** @type {any} */ (indexes).length === 0) {
                // All items fit in viewport (shouldn't happen above threshold, but be safe)
                active = false;
                visible = [];
                topHeight = 0;
                bottomHeight = 0;
                return;
            }

            let [start, end] = indexes;

            start = Math.max(0, start);
            end = Math.min(rowCount - 1, end);

            visible = flatRows.slice(start, end + 1);

            topHeight = start > 0 ? cumHeights[start - 1] : 0;
            bottomHeight =
                end < rowCount - 1 ? cumHeights[rowCount - 1] - cumHeights[end] : 0;

            // Keep the edited record rendered even when scrolled out of the
            // window, as an extra "island" row adjacent to the spacer on its
            // side (NOT by extending the window to include it, which would
            // materialize every row in between). The rows template keys rows
            // by record id, so the row component — and with it focus and
            // pending input — survives island ↔ window transitions. The
            // island renders at the window edge rather than at its true
            // offset, but that slot is beyond the buffer, hence off-screen;
            // the spacer on that side shrinks by the row's height to keep
            // the total scroll height exact.
            const editedRecord = getEditedRecord();
            if (editedRecord) {
                const editedRow = gridState.findRowByRecordId(String(editedRecord.id));
                if (editedRow) {
                    const editIdx = editedRow.globalIndex;
                    if (editIdx < start) {
                        visible = [editedRow, ...visible];
                        topHeight = Math.max(0, topHeight - heights[editIdx]);
                    } else if (editIdx > end) {
                        visible = [...visible, editedRow];
                        bottomHeight = Math.max(0, bottomHeight - heights[editIdx]);
                    }
                }
            }
        },
    };

    return result;
}
