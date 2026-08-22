// @ts-check
/** @odoo-module native */

import { useComponent, useEffect, useExternalListener } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { pick, shallowEqual } from "@web/core/utils/collections/objects";
import { useThrottleForAnimation } from "@web/core/utils/timing";

/**
 * @template T
 * @typedef VirtualGridParams
 * @property {ReturnType<typeof import("@odoo/owl").useRef>} scrollableRef
 * @property {ScrollPosition} [initialScroll={ left: 0, top: 0 }]
 * @property {(changed: Partial<VirtualGridIndexes>) => void} [onChange=() => this.render()]
 * @property {number} [bufferCoef=1]
 * @property {() => number} [getRowsOffset]
 */

/**
 * @typedef VirtualGridIndexes
 * @property {[number, number] | [] | undefined} columnsIndexes
 * @property {[number, number] | [] | undefined} rowsIndexes
 */

/**
 * @typedef VirtualGridSetters
 * @property {(widths: number[]) => void} setColumnsWidths
 * @property {(heights: number[]) => void} setRowsHeights
 */

/**
 * @typedef ScrollPosition
 * @property {number} left
 * @property {number} top
 */

const BUFFER_COEFFICIENT = 1;

const SCROLL_DEADBAND_PX = 4;

/**
 * @typedef GetIndexesParams
 * @property {number[]} [sizes]
 * @property {number} start
 * @property {number} span
 * @property {number} [prevStartIndex]
 * @property {number} [bufferCoef=BUFFER_COEFFICIENT]
 */

/**
 * @param {GetIndexesParams} param0
 * @returns {[number, number] | []}
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

    /**
     * @type {{ scroll: { left: number, top: number }, computedScroll?: { left: number, top: number }, summedColumnsWidths?: number[], summedRowsHeights?: number[], columnsIndexes?: [number, number] | [], rowsIndexes?: [number, number] | [] }}
     */
    const current = { scroll: { left: 0, top: 0, ...initialScroll } };
    const computeColumnsIndexes = () =>
        getIndexes({
            sizes: current.summedColumnsWidths,
            start: Math.abs(current.scroll.left),
            span: scrollableRef.el?.clientWidth || browser.innerWidth,
            prevStartIndex: current.columnsIndexes?.[0],
            bufferCoef,
        });
    const computeRowsIndexes = () =>
        getIndexes({
            sizes: current.summedRowsHeights,
            start: Math.max(0, current.scroll.top - (getRowsOffset?.() ?? 0)),
            span: scrollableRef.el?.clientHeight || browser.innerHeight,
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
