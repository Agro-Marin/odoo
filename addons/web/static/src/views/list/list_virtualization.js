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
const MAX_REMEASURE_RENDERS = 3;

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
    /** @type {HTMLElement | null} */
    let scrollable = null;
    for (
        let node = /** @type {HTMLElement | null} */ (el);
        node;
        node = node.parentElement
    ) {
        if (!SCROLLABLE_OVERFLOWS.has(getComputedStyle(node).overflowY)) {
            continue;
        }
        // remember the nearest declared-scrollable ancestor even when it does
        // not overflow *yet* — it will once the rows are rendered
        scrollable ??= node;
        if (node.scrollHeight > node.clientHeight) {
            return node;
        }
    }
    return scrollable;
}

/**
 * @typedef {import("./list_grid_state").FlatRow} FlatRow
 * @typedef ListVirtualizationConfig
 * @property {any} rootRef
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
 * @param {import("./list_renderer").ListGridContext} ctx
 * @param {ListVirtualizationConfig} config
 * @returns {ListVirtualization}
 */
export function useListVirtualization(
    ctx,
    { rootRef, threshold = DEFAULT_THRESHOLD, bufferCoef = DEFAULT_BUFFER_COEF },
) {
    const { getGridState, canResequence, getEditedRecord } = ctx;
    const component = useComponent();
    let measuredRowHeight = 0;
    let measuredGroupRowHeight = 0;
    let selfRenders = 0;

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
    /** the root `scroller` was resolved from @type {HTMLElement | null} */
    let resolvedFrom = null;
    /** whether a scroller is of any use — set by `refresh` @type {boolean} */
    let needsScroller = false;

    /**
     * `getScrollContainer` reads `getComputedStyle` on every ancestor up to
     * `<html>`, which is a style flush. Every list would otherwise pay it on
     * every patch, including the large majority that stay under the
     * virtualization threshold and never consult the scroller at all. Resolve
     * only while virtualizing, and only once per root element.
     */
    function resolveScroller() {
        if (!needsScroller) {
            return;
        }
        const root = rootRef.el;
        if (root === resolvedFrom && (scroller === null || scroller.isConnected)) {
            return;
        }
        resolvedFrom = root;
        scroller = getScrollContainer(root);
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
            selfRenders = 0;
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
        if (!changed) {
            selfRenders = 0;
            return;
        }
        // This runs from onPatched and renders, so it can re-enter itself. Row
        // heights normally settle in one pass; if they keep changing, a
        // scrollbar (or similar) is toggling with the row count and the two
        // states chase each other forever. Stop re-rendering and keep the last
        // measurement — spacers are then a fraction of a pixel off, which is
        // invisible, whereas the loop is not.
        if (selfRenders >= MAX_REMEASURE_RENDERS) {
            return;
        }
        if (status(component) !== "destroyed") {
            selfRenders++;
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
                needsScroller = false;
                active = false;
                visible = [];
                topHeight = 0;
                bottomHeight = 0;
                return;
            }

            needsScroller = true;
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
