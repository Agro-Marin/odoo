// @ts-check
/** @odoo-module native */

import { markRaw } from "@odoo/owl";

import { DataPoint } from "./datapoint.js";

/** @import { RelationalRecord } from "./record.js" */

/**
 * @typedef {{ position?: "top" | "bottom" }} ListInsertion
 */

/**
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
