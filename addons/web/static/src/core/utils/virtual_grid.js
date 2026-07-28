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
 * @property {() => number} [getRowsOffset]
 *  Distance in px between the scroll container's content origin and the first
 *  row, when the two differ — a sticky header, or a scroll container that is an
 *  ANCESTOR of the grid and holds other content above it. The cumulative sizes
 *  passed to {@link setRowsHeights} are measured from the first row, so without
 *  this the scroll position and those sizes are expressed in different origins
 *  and the computed window is shifted by the offset. Defaults to 0 (the grid
 *  itself is the scroll container and starts at its content origin).
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
 * Scroll movement, in px, below which the visible window is NOT recomputed.
 *
 * Windowing is inherently a fixpoint problem: the indexes are derived from the
 * scroll position, and rendering them changes the scrollable height, which can
 * move the scroll position back. The sizes fed to {@link getIndexes} are
 * *assumed* per-item sizes, while the browser lays out real items at fractional
 * heights and rounds spacer elements — so the assumed and actual extents differ
 * by ~1px, and no exact fixpoint exists.
 *
 * At a scroll extremity the browser additionally clamps the scroll position to
 * `scrollHeight - clientHeight`, which turns that 1px disagreement into a
 * self-sustaining limit cycle: window A renders 1px shorter, the clamp moves
 * the position, the new position selects window B, which renders 1px taller,
 * the clamp moves back, and so on at animation-frame rate forever.
 *
 * A deadband makes the mapping stable under the jitter it causes. Movement is
 * measured against the position the current indexes were computed AT, not the
 * previous event, so many sub-threshold scrolls still accumulate past it. The
 * value only has to exceed the layout rounding error, and is negligible next to
 * the buffer (`bufferCoef` × viewport) that decides when a recompute actually
 * matters.
 */
const SCROLL_DEADBAND_PX = 4;

/**
 * @typedef GetIndexesParams
 * @property {number[]} [sizes] cumulative sizes of the items (each entry sums
 *   the previous sizes and the current item's size). Absent until the caller
 *   has supplied them via `setRowsHeights` / `setColumnsWidths`; `getIndexes`
 *   answers `[]` for that.
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
    if ((sizes.at(-1) ?? 0) < span) {
        return [0, sizes.length - 1];
    }
    const bufferSize = Math.round(span * bufferCoef);
    const bufferStart = start - bufferSize;
    const bufferEnd = start + span + bufferSize;

    let startIndex = prevStartIndex ?? 0;
    while (startIndex > 0 && sizes[startIndex] > bufferStart) {
        startIndex--;
    }
    while (startIndex < sizes.length - 1 && sizes[startIndex] <= bufferStart) {
        startIndex++;
    }

    let endIndex = startIndex;
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
export function useVirtualGrid({
    scrollableRef,
    initialScroll,
    onChange,
    bufferCoef,
    getRowsOffset,
}) {
    const comp = useComponent();
    onChange ||= () => comp.render();

    /** @type {{ scroll: { left: number, top: number }, computedScroll?: { left: number, top: number }, summedColumnsWidths?: number[], summedRowsHeights?: number[], columnsIndexes?: [number, number] | [], rowsIndexes?: [number, number] | [] }} */
    const current = { scroll: { left: 0, top: 0, ...initialScroll } };
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
            start: Math.max(0, current.scroll.top - (getRowsOffset?.() ?? 0)),
            span: scrollableRef.el?.clientHeight || window.innerHeight,
            prevStartIndex: current.rowsIndexes?.[0],
            bufferCoef,
        });
    const throttledCompute = useThrottleForAnimation(() => {
        current.computedScroll = { ...current.scroll };
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
        const computed = current.computedScroll;
        if (
            computed &&
            Math.abs(current.scroll.top - computed.top) < SCROLL_DEADBAND_PX &&
            Math.abs(current.scroll.left - computed.left) < SCROLL_DEADBAND_PX
        ) {
            return;
        }
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
