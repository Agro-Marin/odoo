// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_selection */

import {
    useLongTouchSelection,
    useRecordSelection,
} from "@web/views/multi_record_selection";

/**
 * List-specific composition of the shared multi-record selection layer
 * (`@web/views/multi_record_selection`): the anchor/range/expand core and the
 * long-touch timer come from there; this hook adds the list's own guards
 * (selector availability, touch propagation while a selection exists) and the
 * small-screen selection-mode click handlers.
 *
 * @param {Pick<import("./list_renderer").ListGridContext, "getProps" | "getAllowSelectors" | "toggleRecordSelection" | "getEnv">} ctx
 *   the subset of the grid context this hook reads; the ListRenderer passes its
 *   full `gridContext`.
 * @param {object} config
 * @param {number} config.longTouchThreshold
 * @returns {ReturnType<typeof useRecordSelection> & {
 *   onRowTouchStart: (record: object, ev: TouchEvent) => void,
 *   onRowTouchEnd: (record: object) => void,
 *   onRowTouchMove: (record: object) => void,
 *   resetLongTouchTimer: () => void,
 *   onClickCapture: (record: object, ev: PointerEvent) => void,
 *   ignoreEventInSelectionMode: (ev: MouseEvent) => void,
 * }}
 */
export function useListSelection(ctx, { longTouchThreshold }) {
    const { getProps, getAllowSelectors, toggleRecordSelection, getEnv } = ctx;

    const core = useRecordSelection({
        getRecords: () => getProps().list.records,
    });
    const longTouch = useLongTouchSelection({
        getLongTouchThreshold: () => longTouchThreshold,
        onLongTouch: (record) => toggleRecordSelection(record),
    });

    return Object.assign(core, {
        resetLongTouchTimer() {
            longTouch.resetLongTouchTimer();
        },

        /**
         * @param {object} record
         * @param {TouchEvent} ev
         */
        onRowTouchStart(record, ev) {
            if (!getAllowSelectors()) {
                return;
            }
            if (getProps().list.selection.length) {
                ev.stopPropagation();
            }
            longTouch.onTouchStart(record);
        },

        /**
         * @param {object} _record
         */
        onRowTouchEnd(_record) {
            longTouch.onTouchEnd();
        },

        /**
         * @param {object} _record
         */
        onRowTouchMove(_record) {
            longTouch.onTouchMove();
        },

        /**
         * @param {object} record
         * @param {PointerEvent} ev
         */
        onClickCapture(record, ev) {
            const { list } = getProps();
            if (getEnv().isSmall && list.selection.length) {
                ev.stopPropagation();
                ev.preventDefault();
                toggleRecordSelection(record);
            }
        },

        /**
         * @param {MouseEvent} ev
         */
        ignoreEventInSelectionMode(ev) {
            const { list } = getProps();
            if (getEnv().isSmall && list.selection.length) {
                ev.stopPropagation();
                ev.preventDefault();
            }
        },
    });
}
