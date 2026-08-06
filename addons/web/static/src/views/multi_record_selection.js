// @ts-check
/** @odoo-module native */

/** @module @web/views/multi_record_selection */

import { onWillDestroy, useExternalListener } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { getActiveHotkey } from "@web/core/browser/hotkeys";

/**
 * Renderer-level record-selection core shared by the multi-record views
 * (`MultiRecordController` is the controller-level counterpart). Before this
 * module the list and kanban renderers each carried their own copy of the same
 * three mechanisms, and the copies had drifted:
 *
 * - anchor + range selection ("click, then shift-click selects the span") was
 *   written twice — the list copy resolved the anchor by *object identity*
 *   (`records.indexOf`), so any reload that replaced the record objects
 *   silently degraded shift-click to a single toggle; the kanban copy resolved
 *   by record *id* and survived. The id-based semantics are the correct ones
 *   and are what this hook implements for both views.
 * - long-touch-to-select was written twice with the same timer logic.
 * - modifier-key tracking existed three ways (window shift listeners in the
 *   list, an alt-tracking hook in the kanban, plus `ev.shiftKey` read at click
 *   time). The window-level tracking is unified here; reading the event at
 *   click time is the caller's business.
 *
 * @typedef {object} RecordSelectionContext
 * @property {() => any[]} getRecords
 *   the flat, ordered list of records the range is computed over
 * @property {(record: any) => void} [rangeToggle]
 *   how `toggleSelection` applies a range: defaults to this hook's own
 *   `toggleRangeSelection`; a renderer whose `toggleRangeSelection` is part of
 *   its extension surface passes a delegate to it so subclass overrides keep
 *   catching the call
 * @property {(available: boolean) => void} [onSelectionModifier]
 *   alt-key tracking: called with `true` on an Alt keydown, `false` on any
 *   keyup or window blur (the kanban uses it to reveal selection affordances)
 */

/**
 * @param {any[]} records
 * @param {any} record
 * @returns {number} index of `record` in `records`, resolved by id
 */
function indexOfRecord(records, record) {
    if (!record) {
        return -1;
    }
    return records.findIndex((r) => r.id === record.id);
}

/**
 * @param {RecordSelectionContext} ctx
 * @returns {{
 *   lastCheckedRecord: any,
 *   shiftKeyMode: boolean,
 *   shiftKeyedRecord: any,
 *   isAnchorPresent: () => boolean,
 *   toggleSelection: (record: any, isRange?: boolean) => void,
 *   toggleRangeSelection: (record: any) => void,
 *   expandCheckboxes: (record: any, direction: "up" | "down") => boolean,
 * }}
 */
export function useRecordSelection(ctx) {
    const { getRecords, onSelectionModifier } = ctx;

    const self = {
        /** The range anchor: the record whose checkbox was last toggled. */
        lastCheckedRecord: undefined,

        /** Live shift-key state, tracked at the window level. */
        shiftKeyMode: false,

        /** The record last selected through shift+arrow expansion. */
        shiftKeyedRecord: undefined,

        /**
         * Whether the anchor still designates a rendered record. Resolved by
         * id, so the anchor survives a reload that replaced the record
         * objects.
         *
         * @returns {boolean}
         */
        isAnchorPresent() {
            return indexOfRecord(getRecords(), self.lastCheckedRecord) !== -1;
        },

        /**
         * Single entry point: range-toggle from the anchor when `isRange` and
         * an anchor is present, single toggle otherwise. Always re-anchors on
         * the given record.
         *
         * @param {any} record
         * @param {boolean} [isRange]
         */
        toggleSelection(record, isRange = false) {
            if (isRange && self.isAnchorPresent()) {
                (ctx.rangeToggle || self.toggleRangeSelection)(record);
            } else {
                record.toggleSelection();
            }
            self.lastCheckedRecord = record;
        },

        /**
         * Sets every record between the anchor and `record` (inclusive) to the
         * target state `!record.selected`. Without a resolvable anchor, falls
         * back to a single toggle and re-anchors.
         *
         * @param {any} record
         */
        toggleRangeSelection(record) {
            const records = getRecords();
            const lastCheckedRecordIndex = indexOfRecord(
                records,
                self.lastCheckedRecord,
            );
            if (lastCheckedRecordIndex === -1) {
                self.lastCheckedRecord = record;
                record.toggleSelection(!record.selected);
                return;
            }
            const recordIndex = indexOfRecord(records, record);
            const start = Math.min(recordIndex, lastCheckedRecordIndex);
            const end = Math.max(recordIndex, lastCheckedRecordIndex);
            const selected = !record.selected;
            for (let i = start; i <= end; i++) {
                records[i].toggleSelection(selected);
            }
        },

        /**
         * Shift+arrow selection: grows or shrinks the checked span one record
         * at a time in the given direction.
         *
         * @param {any} record
         * @param {"up" | "down"} direction
         * @returns {boolean} whether the keystroke was handled
         */
        expandCheckboxes(record, direction) {
            const records = getRecords();
            if (!record && direction === "down") {
                const defaultRecord = records[0];
                if (!defaultRecord) {
                    return false;
                }
                self.shiftKeyedRecord = defaultRecord;
                defaultRecord.toggleSelection(true);
                return true;
            }
            const recordIndex = indexOfRecord(records, record);
            const shiftKeyedRecordIndex = indexOfRecord(records, self.shiftKeyedRecord);
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
    };

    useExternalListener(window, "keydown", (ev) => {
        self.shiftKeyMode = ev.shiftKey;
        if (ev.key === "Alt") {
            onSelectionModifier?.(true);
        }
    });
    useExternalListener(window, "keyup", (ev) => {
        self.shiftKeyMode = ev.shiftKey;
        if (getActiveHotkey(ev) === "shift") {
            self.shiftKeyedRecord = undefined;
        }
        onSelectionModifier?.(false);
    });
    useExternalListener(window, "blur", () => {
        self.shiftKeyMode = false;
        onSelectionModifier?.(false);
    });

    return self;
}

/**
 * Long-touch-to-select timer: arms on touch start, fires `onLongTouch` after
 * the threshold, disarms on early release or on any move/cancel. The pending
 * timer is cleared when the owning component is destroyed, so a touch-and-hold
 * followed by a navigation cannot toggle selection on a torn-down view.
 *
 * @param {object} config
 * @param {() => number} config.getLongTouchThreshold in milliseconds
 * @param {(record: any) => void} config.onLongTouch
 * @returns {{
 *   onTouchStart: (record?: any) => void,
 *   onTouchEnd: () => void,
 *   onTouchMove: () => void,
 *   resetLongTouchTimer: () => void,
 * }}
 */
export function useLongTouchSelection({ getLongTouchThreshold, onLongTouch }) {
    let longTouchTimer = null;
    let touchStartMs = 0;

    const self = {
        resetLongTouchTimer() {
            if (longTouchTimer) {
                browser.clearTimeout(longTouchTimer);
                longTouchTimer = null;
            }
        },

        /**
         * @param {any} [record] forwarded to `onLongTouch`
         */
        onTouchStart(record) {
            touchStartMs = Date.now();
            if (longTouchTimer === null) {
                longTouchTimer = browser.setTimeout(() => {
                    onLongTouch(record);
                    self.resetLongTouchTimer();
                }, getLongTouchThreshold());
            }
        },

        onTouchEnd() {
            const elapsedTime = Date.now() - touchStartMs;
            if (elapsedTime < getLongTouchThreshold()) {
                self.resetLongTouchTimer();
            }
        },

        onTouchMove() {
            self.resetLongTouchTimer();
        },
    };

    onWillDestroy(() => self.resetLongTouchTimer());

    return self;
}
