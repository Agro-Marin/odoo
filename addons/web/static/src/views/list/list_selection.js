// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_selection */

import { onWillDestroy, useExternalListener } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { getActiveHotkey } from "@web/core/browser/hotkeys";

/**
 * @param {Pick<import("./list_renderer").ListGridContext, "getProps" | "getAllowSelectors" | "toggleRecordSelection" | "getEnv">} ctx
 *   the subset of the grid context this hook reads; the ListRenderer passes its
 *   full `gridContext`.
 * @param {object} config
 * @param {number} config.longTouchThreshold
 * @returns {{
 *   toggleRangeSelection: (record: object) => void,
 *   expandCheckboxes: (record: object, direction: "up" | "down") => boolean,
 *   onRowTouchStart: (record: object, ev: TouchEvent) => void,
 *   onRowTouchEnd: (record: object) => void,
 *   onRowTouchMove: (record: object) => void,
 *   resetLongTouchTimer: () => void,
 *   onClickCapture: (record: object, ev: PointerEvent) => void,
 *   ignoreEventInSelectionMode: (ev: MouseEvent) => void,
 *   shiftKeyMode: boolean,
 *   shiftKeyedRecord: object | undefined,
 *   lastCheckedRecord: object | undefined,
 * }}
 */
export function useListSelection(ctx, { longTouchThreshold }) {
    const { getProps, getAllowSelectors, toggleRecordSelection, getEnv } = ctx;
    let longTouchTimer = null;
    let touchStartMs = 0;

    const self = {
        shiftKeyMode: false,

        shiftKeyedRecord: undefined,

        lastCheckedRecord: undefined,

        resetLongTouchTimer() {
            if (longTouchTimer) {
                browser.clearTimeout(longTouchTimer);
                longTouchTimer = null;
            }
        },

        /**
         * @param {object} record
         */
        toggleRangeSelection(record) {
            const { records } = getProps().list;
            const recordIndex = records.indexOf(record);
            const lastCheckedRecordIndex = records.indexOf(self.lastCheckedRecord);
            if (lastCheckedRecordIndex === -1) {
                self.lastCheckedRecord = record;
                record.toggleSelection(!record.selected);
                return;
            }
            const start = Math.min(recordIndex, lastCheckedRecordIndex);
            const end = Math.max(recordIndex, lastCheckedRecordIndex);
            const selected = !record.selected;
            for (let i = start; i <= end; i++) {
                records[i].toggleSelection(selected);
            }
        },

        /**
         * @param {object} record
         * @param {"up" | "down"} direction
         * @returns {boolean}
         */
        expandCheckboxes(record, direction) {
            const { records } = getProps().list;
            if (!record && direction === "down") {
                const defaultRecord = records[0];
                if (!defaultRecord) {
                    return false;
                }
                self.shiftKeyedRecord = defaultRecord;
                defaultRecord.toggleSelection(true);
                return true;
            }
            const recordIndex = records.indexOf(record);
            const shiftKeyedRecordIndex = records.indexOf(self.shiftKeyedRecord);
            let nextRecord;
            let isExpanding;
            switch (direction) {
                case "up":
                    if (recordIndex <= 0) {
                        return false;
                    }
                    nextRecord = records[recordIndex - 1];
                    isExpanding = shiftKeyedRecordIndex > recordIndex - 1;
                    break;
                case "down":
                    if (recordIndex === records.length - 1) {
                        return false;
                    }
                    nextRecord = records[recordIndex + 1];
                    isExpanding = shiftKeyedRecordIndex < recordIndex + 1;
                    break;
            }

            if (isExpanding) {
                record.toggleSelection(true);
                nextRecord.toggleSelection(true);
            } else {
                record.toggleSelection(false);
            }
            return true;
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
            touchStartMs = Date.now();
            if (longTouchTimer === null) {
                longTouchTimer = browser.setTimeout(() => {
                    toggleRecordSelection(record);
                    self.resetLongTouchTimer();
                }, longTouchThreshold);
            }
        },

        /**
         * @param {object} _record
         */
        onRowTouchEnd(_record) {
            const elapsedTime = Date.now() - touchStartMs;
            if (elapsedTime < longTouchThreshold) {
                self.resetLongTouchTimer();
            }
        },

        /**
         * @param {object} _record
         */
        onRowTouchMove(_record) {
            self.resetLongTouchTimer();
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
    };

    useExternalListener(window, "keydown", (ev) => {
        self.shiftKeyMode = ev.shiftKey;
    });
    useExternalListener(window, "keyup", (ev) => {
        self.shiftKeyMode = ev.shiftKey;
        if (getActiveHotkey(ev) === "shift") {
            self.shiftKeyedRecord = undefined;
        }
    });
    useExternalListener(window, "blur", () => {
        self.shiftKeyMode = false;
    });
    onWillDestroy(() => self.resetLongTouchTimer());

    return self;
}
