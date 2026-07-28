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

import { onMounted, onPatched, status, useComponent } from "@odoo/owl";
import { useVirtualGrid } from "@web/core/utils/virtual_grid";
const DEFAULT_ROW_HEIGHT = 41;
const DEFAULT_GROUP_ROW_HEIGHT = 37;
const DEFAULT_THRESHOLD = 100;
const DEFAULT_BUFFER_COEF = 0.5;
/**
 * Sub-pixel granularity of a measured row height. Row heights ARE fractional
 * (40.5px at default density), and the measurement feeds back into a
 * ``component.render()`` — so comparing raw floats makes any sub-pixel jitter
 * (zoom level, fractional borders, a scrollbar appearing) a render trigger,
 * with no bound on how often it can fire. Quantizing to a quarter pixel keeps
 * every real density change detectable while making jitter a no-op.
 */
const HEIGHT_QUANTUM = 0.25;

/**
 * @param {number} height
 * @returns {number}
 */
function quantize(height) {
    return Math.round(height / HEIGHT_QUANTUM) * HEIGHT_QUANTUM;
}

/**
 * @typedef {import("./list_grid_state").FlatRow} FlatRow
 *
 * @typedef ListVirtualizationOptions
 * @property {any} rootRef - ref to .o_list_renderer
 * @property {() => import("./list_grid_state").ListGridState} getGridState
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
    canResequence,
    getEditedRecord,
    threshold = DEFAULT_THRESHOLD,
    bufferCoef = DEFAULT_BUFFER_COEF,
}) {
    const component = useComponent();
    let measuredRowHeight = 0;
    let measuredGroupRowHeight = 0;

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
     *
     * The geometry produced by {@link refresh} (spacer heights, cumulative
     * offsets, the visible window) is derived from these two numbers, and the
     * render that first activates virtualization necessarily ran before any
     * row existed to measure — so it used the DEFAULT_* constants. Those are
     * only right at default density; `o-density-compact` / `o-density-condensed`
     * (and any addon restyling rows) make them wrong by tens of percent, which
     * shows up as a scrollable extent that does not match the rows.
     *
     * Measuring therefore has to feed back into a render: without it the stale
     * geometry survives until an unrelated render happens to re-enter
     * `refresh()`. Re-rendering converges in one extra pass — the following
     * `onPatched` measures the same heights and requests nothing.
     */
    function measureRowHeights() {
        const el = rootRef.el;
        if (!el) {
            return;
        }
        if (!active) {
            return;
        }
        let changed = false;
        const dataRow = el.querySelector(".o_data_row");
        if (dataRow) {
            const rowHeight =
                quantize(dataRow.getBoundingClientRect().height) || DEFAULT_ROW_HEIGHT;
            if (rowHeight !== measuredRowHeight) {
                measuredRowHeight = rowHeight;
                changed = true;
            }
        }
        const groupRow = el.querySelector(".o_group_header");
        if (groupRow) {
            const groupHeight =
                quantize(groupRow.getBoundingClientRect().height) ||
                DEFAULT_GROUP_ROW_HEIGHT;
            if (groupHeight !== measuredGroupRowHeight) {
                measuredGroupRowHeight = groupHeight;
                changed = true;
            }
        }
        if (changed && status(component) !== "destroyed") {
            component.render();
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
            const scrollTo = Math.max(0, targetTop - containerHeight / 2);
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
                cumHeights = new Array(rowCount);
                let acc = 0;
                for (let i = 0; i < rowCount; i++) {
                    acc += heights[i];
                    cumHeights[i] = acc;
                }
            }

            const indexes = virtualGrid.rowsIndexes;
            if (!indexes || /** @type {any} */ (indexes).length === 0) {
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
