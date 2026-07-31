// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_virtualization */

import { onMounted, onPatched, status, useComponent } from "@odoo/owl";
import { useVirtualGrid } from "@web/core/utils/virtual_grid";
const DEFAULT_ROW_HEIGHT = 41;
const DEFAULT_GROUP_ROW_HEIGHT = 37;
export const DEFAULT_THRESHOLD = 100;
const DEFAULT_BUFFER_COEF = 0.5;
const HEIGHT_QUANTUM = 0.25;

/**
 * @param {number} height
 * @returns {number}
 */
function quantize(height) {
    return Math.round(height / HEIGHT_QUANTUM) * HEIGHT_QUANTUM;
}

const SCROLLABLE_OVERFLOWS = new Set(["auto", "scroll", "overlay"]);

/**
 * @param {HTMLElement | null | undefined} el
 * @returns {HTMLElement | null}
 */
function getScrollContainer(el) {
    if (!el) {
        return null;
    }
    for (
        let node = /** @type {HTMLElement | null} */ (el);
        node;
        node = node.parentElement
    ) {
        if (
            node.scrollHeight > node.clientHeight &&
            SCROLLABLE_OVERFLOWS.has(getComputedStyle(node).overflowY)
        ) {
            return node;
        }
    }
    return el;
}

/**
 * @typedef {import("./list_grid_state").FlatRow} FlatRow
 * @typedef ListVirtualizationOptions
 * @property {any} rootRef
 * @property {() => import("./list_grid_state").ListGridState} getGridState
 * @property {() => boolean} canResequence
 * @property {() => { id: string | number } | null} getEditedRecord
 * @property {number} [threshold]
 * @property {number} [bufferCoef]
 */

/**
 * @typedef ListVirtualization
 * @property {boolean} isActive
 * @property {FlatRow[]} visibleFlatRows
 * @property {number} topSpacerHeight
 * @property {number} bottomSpacerHeight
 * @property {(rowIndex: number) => void} ensureRowVisible
 * @property {() => void} refresh
 */

/**
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

    /** @type {HTMLElement | null} */
    let scroller = null;
    function resolveScroller() {
        scroller = getScrollContainer(rootRef.el);
    }
    onMounted(resolveScroller);
    onPatched(resolveScroller);

    const scrollableRef = {
        get el() {
            return scroller;
        },
    };

    /**
     * @returns {number}
     */
    function getRowsOffset() {
        const scroller = scrollableRef.el;
        const tbody = rootRef.el?.querySelector("tbody");
        if (!scroller || !tbody) {
            return 0;
        }
        return Math.max(
            0,
            tbody.getBoundingClientRect().top -
                scroller.getBoundingClientRect().top +
                scroller.scrollTop,
        );
    }

    const virtualGrid = useVirtualGrid({
        scrollableRef,
        bufferCoef,
        getRowsOffset,
    });

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
         * @param {number} rowIndex
         */
        ensureRowVisible(rowIndex) {
            const scroller = scrollableRef.el;
            if (!active || !scroller) {
                return;
            }
            if (rowIndex < 0 || rowIndex >= cumHeights.length) {
                return;
            }
            const targetTop =
                (rowIndex > 0 ? cumHeights[rowIndex - 1] : 0) + getRowsOffset();
            const containerHeight = scroller.clientHeight;
            const scrollTo = Math.max(0, targetTop - containerHeight / 2);
            scroller.scrollTop = scrollTo;
        },

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

            let heightsChanged = rowCount !== heights.length;
            for (let i = 0; !heightsChanged && i < rowCount; i++) {
                heightsChanged =
                    heights[i] !== (flatRows[i].type === "group" ? groupH : rowH);
            }

            if (heightsChanged) {
                heights = new Array(rowCount);
                cumHeights = new Array(rowCount);
                let acc = 0;
                for (let i = 0; i < rowCount; i++) {
                    heights[i] = flatRows[i].type === "group" ? groupH : rowH;
                    acc += heights[i];
                    cumHeights[i] = acc;
                }
                virtualGrid.setRowsHeights(heights);
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
