// @ts-check
/** @odoo-module native */

import { markRaw, toRaw, useExternalListener, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { pick, shallowEqual } from "@web/core/utils/collections/objects";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { useThrottleForAnimation } from "@web/core/utils/timing";

/**
 * @typedef VirtualGridParams
 * @property {ReturnType<typeof import("@odoo/owl").useRef>} scrollableRef
 * @property {ScrollPosition} [initialScroll={ left: 0, top: 0 }]
 * @property {(changed: Partial<VirtualGridIndexes>) => void} [onChange]
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
 * @param {VirtualGridParams} params
 * @returns {VirtualGridIndexes & VirtualGridSetters}
 */
export function useVirtualGrid({
    scrollableRef,
    initialScroll,
    onChange,
    bufferCoef,
    getRowsOffset,
}) {
    const visible = useState({
        /** @type {[number, number] | [] | undefined} */
        columnsIndexes: undefined,
        /** @type {[number, number] | [] | undefined} */
        rowsIndexes: undefined,
    });
    /**
     * @param {"columnsIndexes" | "rowsIndexes"} key
     * @param {[number, number] | []} indexes
     * @returns {boolean}
     */
    const setVisible = (key, indexes) => {
        current[key] = indexes;
        if (shallowEqual(indexes, toRaw(visible)[key])) {
            return false;
        }
        visible[key] = markRaw(indexes);
        return true;
    };

    /** @type {{ scroll: { left: number, top: number }, computedScroll?: { left: number, top: number }, summedColumnsWidths?: number[], summedRowsHeights?: number[], columnsIndexes?: [number, number] | [], rowsIndexes?: [number, number] | [] }} */
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
        if (setVisible("columnsIndexes", computeColumnsIndexes())) {
            changed.push("columnsIndexes");
        }
        if (setVisible("rowsIndexes", computeRowsIndexes())) {
            changed.push("rowsIndexes");
        }
        if (changed.length) {
            onChange?.(pick(current, .../** @type {any} */ (changed)));
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
    useLayoutEffect(
        (el) => {
            el?.addEventListener("scroll", scrollListener);
            return () => el?.removeEventListener("scroll", scrollListener);
        },
        () => [scrollableRef.el],
    );
    useExternalListener(window, "resize", () => throttledCompute());
    return {
        get columnsIndexes() {
            return visible.columnsIndexes;
        },
        get rowsIndexes() {
            return visible.rowsIndexes;
        },
        setColumnsWidths(widths) {
            let acc = 0;
            current.summedColumnsWidths = widths.map((w) => (acc += w));
            delete current.columnsIndexes;
            setVisible("columnsIndexes", computeColumnsIndexes());
        },
        setRowsHeights(heights) {
            let acc = 0;
            current.summedRowsHeights = heights.map((h) => (acc += h));
            delete current.rowsIndexes;
            setVisible("rowsIndexes", computeRowsIndexes());
        },
    };
}
