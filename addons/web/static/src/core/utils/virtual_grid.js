// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/virtual_grid - useVirtualGrid hook for windowed rendering of large row/column grids */

import { useComponent, useEffect, useExternalListener } from "@odoo/owl";
import { pick, shallowEqual } from "@web/core/utils/collections/objects";
import { useThrottleForAnimation } from "@web/core/utils/timing";

/**
 * @template T
 * @typedef VirtualGridParams
 * @property {ReturnType<typeof import("@odoo/owl").useRef>} scrollableRef
 *  a ref to the scrollable element
 * @property {ScrollPosition} [initialScroll={ left: 0, top: 0 }]
 *  the initial scroll position of the scrollable element
 * @property {(changed: Partial<VirtualGridIndexes>) => void} [onChange=() => this.render()]
 *  called when the visible items change (scroll/resize); defaults to re-rendering the component.
 * @property {number} [bufferCoef=1]
 *  buffer size around the visible area, as a multiple of the window size on each side.
 *  Default 1 renders 3x the window size (9x if buffered on both axes); 0 means no buffer.
 *  Lower it for costly renders.
 */

/**
 * @typedef VirtualGridIndexes
 * @property {[number, number] | [] | undefined} columnsIndexes
 * @property {[number, number] | [] | undefined} rowsIndexes
 */

/**
 * @typedef VirtualGridSetters
 * @property {(widths: number[]) => void} setColumnsWidths
 *  Set the width of each column (indexes must match column indexes).
 * @property {(heights: number[]) => void} setRowsHeights
 *  Set the height of each row (indexes must match row indexes).
 */

/**
 * @typedef ScrollPosition
 * @property {number} left
 * @property {number} top
 */

const BUFFER_COEFFICIENT = 1;

/**
 * @typedef GetIndexesParams
 * @property {number[]} sizes cumulative sizes of the items (each entry sums the previous sizes and the current item's size).
 * @property {number} start start of the visible area (scroll position).
 * @property {number} span size of the visible area (window size).
 * @property {number} [prevStartIndex] previous start index, used to optimize the search.
 * @property {number} [bufferCoef=BUFFER_COEFFICIENT] coefficient to calculate the buffer size.
 */

/**
 * Calculates the indexes of the visible items in a virtual list.
 *
 * @param {GetIndexesParams} param0
 * @returns {[number, number] | []} the indexes of the visible items with a surrounding buffer of totalSize on each side.
 */
function getIndexes({
    sizes,
    start,
    span,
    prevStartIndex,
    bufferCoef = BUFFER_COEFFICIENT,
}) {
    if (!sizes || !sizes.length) {
        return [];
    }
    if (sizes.at(-1) < span) {
        // all items could be displayed
        return [0, sizes.length - 1];
    }
    const bufferSize = Math.round(span * bufferCoef);
    const bufferStart = start - bufferSize;
    const bufferEnd = start + span + bufferSize;

    let startIndex = prevStartIndex ?? 0;
    // we search the first index such that sizes[index] > bufferStart
    while (startIndex > 0 && sizes[startIndex] > bufferStart) {
        startIndex--;
    }
    while (startIndex < sizes.length - 1 && sizes[startIndex] <= bufferStart) {
        startIndex++;
    }

    let endIndex = startIndex;
    // we search the last index such that (sizes[index - 1] ?? 0) < bufferEnd
    while (endIndex < sizes.length - 1 && (sizes[endIndex - 1] ?? 0) < bufferEnd) {
        endIndex++;
    }
    while (endIndex > startIndex && (sizes[endIndex - 1] ?? 0) >= bufferEnd) {
        endIndex--;
    }
    return [startIndex, endIndex];
}

/**
 * Calculates the displayed items in a virtual grid.
 *
 * Requirements:
 *  - the scrollable area has a fixed height and width.
 *  - the items are rendered with a proper offset inside the scrollable area.
 *    This can be achieved e.g. with a css grid or an absolute positioning.
 *
 * @template T
 * @param {VirtualGridParams<T>} params
 * @returns {VirtualGridIndexes & VirtualGridSetters}
 */
export function useVirtualGrid({ scrollableRef, initialScroll, onChange, bufferCoef }) {
    const comp = useComponent();
    onChange ||= () => comp.render();

    /** @type {{ scroll: { left: number, top: number }, summedColumnsWidths?: number[], summedRowsHeights?: number[], columnsIndexes?: [number, number] | [], rowsIndexes?: [number, number] | [] }} */
    const current = { scroll: { left: 0, top: 0, ...initialScroll } };
    // The visible span is the scrollable's own client box, not the window:
    // for a small pane (e.g. a grid in a dialog or side panel) the window
    // span can be several times larger, rendering up to ~4x the needed DOM.
    // Fall back to the window dimensions when the element has no layout yet
    // (or the ref is not mounted).
    const computeColumnsIndexes = () =>
        getIndexes({
            sizes: current.summedColumnsWidths,
            start: Math.abs(current.scroll.left),
            span: scrollableRef.el?.clientWidth || window.innerWidth,
            prevStartIndex: current.columnsIndexes?.[0],
            bufferCoef,
        });
    const computeRowsIndexes = () =>
        getIndexes({
            sizes: current.summedRowsHeights,
            start: current.scroll.top,
            span: scrollableRef.el?.clientHeight || window.innerHeight,
            prevStartIndex: current.rowsIndexes?.[0],
            bufferCoef,
        });
    const throttledCompute = useThrottleForAnimation(() => {
        const changed = [];
        const columnsVisibleIndexes = computeColumnsIndexes();
        if (!shallowEqual(columnsVisibleIndexes, current.columnsIndexes)) {
            current.columnsIndexes = columnsVisibleIndexes;
            changed.push("columnsIndexes");
        }
        const rowsVisibleIndexes = computeRowsIndexes();
        if (!shallowEqual(rowsVisibleIndexes, current.rowsIndexes)) {
            current.rowsIndexes = rowsVisibleIndexes;
            changed.push("rowsIndexes");
        }
        if (changed.length) {
            onChange(pick(current, .../** @type {any} */ (changed)));
        }
    });
    const scrollListener = (/** @type {Event} */ ev) => {
        const target = /** @type {Element} */ (ev.target);
        current.scroll.left = target.scrollLeft;
        current.scroll.top = target.scrollTop;
        throttledCompute();
    };
    useEffect(
        (el) => {
            el?.addEventListener("scroll", scrollListener);
            return () => el?.removeEventListener("scroll", scrollListener);
        },
        () => [scrollableRef.el],
    );
    useExternalListener(window, "resize", () => throttledCompute());
    return {
        get columnsIndexes() {
            return current.columnsIndexes;
        },
        get rowsIndexes() {
            return current.rowsIndexes;
        },
        setColumnsWidths(widths) {
            let acc = 0;
            current.summedColumnsWidths = widths.map((w) => (acc += w));
            delete current.columnsIndexes;
            current.columnsIndexes = computeColumnsIndexes();
        },
        setRowsHeights(heights) {
            let acc = 0;
            current.summedRowsHeights = heights.map((h) => (acc += h));
            delete current.rowsIndexes;
            current.rowsIndexes = computeRowsIndexes();
        },
    };
}
