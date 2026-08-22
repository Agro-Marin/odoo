// @ts-check
/** @odoo-module native */

/**
 * @type {string[]}
 */
export const DYNAMIC_LIST_OWNER_SURFACE = [
    "_multiSave",
    "_resequence",
    "_isRecordToDiscard",
    "_onRecordDeselected",
];

/**
 * @typedef {{
 * _multiSave: (editedRecord: any, changes: any) => Promise<any>,
 * _resequence: (originalList: any[], resModel: string, movedId: any, targetId: any) => Promise<any>,
 * _isRecordToDiscard: (record: any) => boolean,
 * _onRecordDeselected: () => void,
 * }} DynamicListContract
 */
