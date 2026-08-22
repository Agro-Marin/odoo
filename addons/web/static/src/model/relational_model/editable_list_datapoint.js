// @ts-check
/** @odoo-module native */

import { markRaw } from "@odoo/owl";

import { DataPoint } from "./datapoint.js";

/** @import { RelationalRecord } from "./record.js" */

/**
 * @typedef {{ position?: "top" | "bottom" }} ListInsertion
 */

/**
 * The datapoint layer shared by the two lists that own records and an edit
 * mode: `DynamicList` (a server-backed list) and `StaticList` (an x2many).
 *
 * It exists for the edit-mode handover. `editedRecord` is derived from the
 * records themselves, so it is momentarily `undefined` inside `enterEditMode`:
 * between the outgoing record leaving edition and the incoming one entering it,
 * no record answers `isInEdition`. A renderer reading `isEditing` in that gap
 * sees `false`, so the flag publishes `true -> false -> true` for a state no
 * frame ever shows — which repainted every row twice on a 40-row list, 81 row
 * renders where 4 were needed (`machine_doc_v1/LIST_EDIT_RENDER_COST.md`).
 *
 * The handover slot spans the gap: whoever moves edition declares the incoming
 * record before the outgoing one leaves, and `isEditing` stays `true`
 * throughout. The holder is `markRaw` on purpose — it must not be reactive, or
 * writing it would notify every subscriber and reintroduce the repaint it
 * exists to prevent.
 *
 * This is a class rather than a mixin because both lists are `// @ts-check`ed
 * and a JS mixin factory erases the base type: expressing it as
 * `EditHandoverMixin(DataPoint)` cost ~200 `tsc` errors across the two lists
 * and `DynamicGroupList`, for the same twenty lines of sharing.
 *
 * @abstract
 */
export class EditableListDataPoint extends DataPoint {
    /**
     * @type {{ record: RelationalRecord | null }}
     */
    _editHandover = markRaw({ record: null });

    /**
     * @returns {RelationalRecord | undefined}
     */
    get editedRecord() {
        return /** @type {RelationalRecord[]} */ (
            /** @type {any} */ (this).records
        ).find((record) => record.isInEdition);
    }

    /**
     * @returns {boolean}
     */
    get isEditing() {
        return Boolean(this._editHandover.record || this.editedRecord);
    }

    /**
     * @param {RelationalRecord} record
     * @returns {() => void}
     */
    beginEditHandover(record) {
        this._editHandover.record = record;
        return () => {
            this._editHandover.record = null;
        };
    }

    /**
     * @returns {string | undefined}
     */
    _findHandleField() {
        return Object.keys(this.activeFields).find(
            (fieldName) => this.activeFields[fieldName].isHandle,
        );
    }

    /**
     * @param {string|number} dataRecordId
     * @param {string} [_dataGroupId]
     * @param {string|number} [refId]
     * @param {string} [_targetGroupId]
     * @returns {Promise<any>}
     */
    moveRecord(dataRecordId, _dataGroupId, refId, _targetGroupId) {
        return /** @type {any} */ (this).resequence(dataRecordId, refId);
    }
}
