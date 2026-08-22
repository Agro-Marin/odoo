// @ts-check
/** @odoo-module native */

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

export class ListVirtualization {
    /** @type {boolean} */
    active = false;
    /** @type {FlatRow[]} */
    visible = [];
    /** @type {number} */
    topHeight = 0;
    /** @type {number} */
    bottomHeight = 0;
    /** @type {number[]} */
    heights = [];
    /** @type {number[]} */
    cumHeights = [];
    /** @type {number} */
    measuredRowHeight = 0;
    /** @type {number} */
    measuredGroupRowHeight = 0;
    /** @type {number} */
    selfRenders = 0;
    /** @type {HTMLElement | null} */
    scroller = null;
    /** @type {HTMLElement | null} */
    resolvedFrom = null;
    /** @type {boolean} */
    needsScroller = false;

    /**
     * @param {Pick<
     * import("./list_renderer").ListGridContext,
     * "getGridState" | "canResequence" | "getEditedRecord"
     * >} ctx
     * @param {object} params
     * @param {any} params.rootRef
     * @param {any} params.component
     * @param {number} params.threshold
     */
    constructor(ctx, { rootRef, component, threshold }) {
        this.ctx = ctx;
        this.rootRef = rootRef;
        this.component = component;
        this.threshold = threshold;
        /** @type {{ readonly el: HTMLElement | null }} */
        this.scrollableRef = { el: null };
        Object.defineProperty(this.scrollableRef, "el", {
            get: () => this.scroller,
        });
    }

    /**
     * @param {any} virtualGrid
     */
    setVirtualGrid(virtualGrid) {
        this.virtualGrid = virtualGrid;
    }

    /** @returns {boolean} */
    get isActive() {
        return this.active;
    }

    /** @returns {FlatRow[]} */
    get visibleFlatRows() {
        return this.visible;
    }

    /** @returns {number} */
    get topSpacerHeight() {
        return this.topHeight;
    }

    /** @returns {number} */
    get bottomSpacerHeight() {
        return this.bottomHeight;
    }

    resolveScroller() {
        if (!this.needsScroller) {
            return;
        }
        const root = this.rootRef.el;
        if (
            root === this.resolvedFrom &&
            (this.scroller === null || this.scroller.isConnected)
        ) {
            return;
        }
        this.resolvedFrom = root;
        this.scroller = getScrollContainer(root);
    }

    /**
     * @returns {number}
     */
    getRowsOffset() {
        const scroller = this.scroller;
        const tbody = this.rootRef.el?.querySelector("tbody");
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

    measureRowHeights() {
        const el = this.rootRef.el;
        if (!el) {
            return;
        }
        if (!this.active) {
            this.selfRenders = 0;
            return;
        }
        let changed = false;
        const dataRow = el.querySelector(".o_data_row");
        if (dataRow) {
            const rowHeight =
                quantize(dataRow.getBoundingClientRect().height) || DEFAULT_ROW_HEIGHT;
            if (rowHeight !== this.measuredRowHeight) {
                this.measuredRowHeight = rowHeight;
                changed = true;
            }
        }
        const groupRow = el.querySelector(".o_group_header");
        if (groupRow) {
            const groupHeight =
                quantize(groupRow.getBoundingClientRect().height) ||
                DEFAULT_GROUP_ROW_HEIGHT;
            if (groupHeight !== this.measuredGroupRowHeight) {
                this.measuredGroupRowHeight = groupHeight;
                changed = true;
            }
        }
        if (!changed) {
            this.selfRenders = 0;
            return;
        }
        if (this.selfRenders >= MAX_REMEASURE_RENDERS) {
            return;
        }
        if (status(this.component) !== "destroyed") {
            this.selfRenders++;
            this.component.render();
        }
    }

    /**
     * @param {number} rowIndex
     */
    ensureRowVisible(rowIndex) {
        const scroller = this.scroller;
        if (!this.active || !scroller) {
            return;
        }
        if (rowIndex < 0 || rowIndex >= this.cumHeights.length) {
            return;
        }
        const targetTop =
            (rowIndex > 0 ? this.cumHeights[rowIndex - 1] : 0) + this.getRowsOffset();
        scroller.scrollTop = Math.max(0, targetTop - scroller.clientHeight / 2);
    }

    deactivate() {
        this.active = false;
        this.visible = [];
        this.topHeight = 0;
        this.bottomHeight = 0;
    }

    /**
     * @param {FlatRow[]} flatRows
     * @param {number} rowH
     * @param {number} groupH
     */
    syncHeights(flatRows, rowH, groupH) {
        const rowCount = flatRows.length;
        let heightsChanged = rowCount !== this.heights.length;
        for (let i = 0; !heightsChanged && i < rowCount; i++) {
            heightsChanged =
                this.heights[i] !== (flatRows[i].type === "group" ? groupH : rowH);
        }
        if (!heightsChanged) {
            return;
        }
        this.heights = new Array(rowCount);
        this.cumHeights = new Array(rowCount);
        let acc = 0;
        for (let i = 0; i < rowCount; i++) {
            this.heights[i] = flatRows[i].type === "group" ? groupH : rowH;
            acc += this.heights[i];
            this.cumHeights[i] = acc;
        }
        this.virtualGrid.setRowsHeights(this.heights);
    }

    /**
     * @param {import("./list_grid_state").ListGridState} gridState
     * @param {number} start
     * @param {number} end
     */
    keepEditedRowVisible(gridState, start, end) {
        const editedRecord = this.ctx.getEditedRecord();
        if (!editedRecord) {
            return;
        }
        const editedRow = gridState.findRowByRecordId(String(editedRecord.id));
        if (!editedRow) {
            return;
        }
        const editIdx = editedRow.globalIndex;
        if (editIdx < start) {
            this.visible = [editedRow, ...this.visible];
            this.topHeight = Math.max(0, this.topHeight - this.heights[editIdx]);
        } else if (editIdx > end) {
            this.visible = [...this.visible, editedRow];
            this.bottomHeight = Math.max(0, this.bottomHeight - this.heights[editIdx]);
        }
    }

    refresh() {
        const gridState = this.ctx.getGridState();
        const flatRows = gridState.flatRows;
        const rowCount = flatRows.length;

        if (rowCount <= this.threshold || this.ctx.canResequence()) {
            this.needsScroller = false;
            this.deactivate();
            return;
        }

        this.needsScroller = true;
        this.active = true;

        this.syncHeights(
            flatRows,
            this.measuredRowHeight || DEFAULT_ROW_HEIGHT,
            this.measuredGroupRowHeight || DEFAULT_GROUP_ROW_HEIGHT,
        );

        const indexes = this.virtualGrid.rowsIndexes;
        if (!indexes || /** @type {any} */ (indexes).length === 0) {
            this.deactivate();
            return;
        }

        const start = Math.max(0, indexes[0]);
        const end = Math.min(rowCount - 1, indexes[1]);

        this.visible = flatRows.slice(start, end + 1);
        this.topHeight = start > 0 ? this.cumHeights[start - 1] : 0;
        this.bottomHeight =
            end < rowCount - 1
                ? this.cumHeights[rowCount - 1] - this.cumHeights[end]
                : 0;

        this.keepEditedRowVisible(gridState, start, end);
    }
}

/**
 * @param {Pick<
 * import("./list_renderer").ListGridContext,
 * "getGridState" | "canResequence" | "getEditedRecord"
 * >} ctx
 * @param {ListVirtualizationConfig} config
 * @returns {ListVirtualization}
 */
export function useListVirtualization(
    ctx,
    { rootRef, threshold = DEFAULT_THRESHOLD, bufferCoef = DEFAULT_BUFFER_COEF },
) {
    const virt = new ListVirtualization(ctx, {
        rootRef,
        component: useComponent(),
        threshold,
    });
    virt.setVirtualGrid(
        useVirtualGrid({
            scrollableRef: virt.scrollableRef,
            bufferCoef,
            getRowsOffset: () => virt.getRowsOffset(),
        }),
    );
    onMounted(() => virt.resolveScroller());
    onPatched(() => virt.resolveScroller());
    onMounted(() => virt.measureRowHeights());
    onPatched(() => virt.measureRowHeights());
    return virt;
}
