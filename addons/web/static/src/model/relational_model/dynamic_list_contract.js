// @ts-check
/** @odoo-module native */

/**
 * @type {string[]}
 */
export const DYNAMIC_LIST_OWNER_SURFACE = [
    "multiSaveLocked",
    "resequenceLocked",
    "isRecordToDiscard",
    "onRecordDeselected",
];

/**
 * @typedef {{
 * multiSaveLocked: (editedRecord: any, changes: any) => Promise<any>,
 * resequenceLocked: (originalList: any[], resModel: string, movedId: any, targetId: any) => Promise<any>,
 * isRecordToDiscard: (record: any) => boolean,
 * onRecordDeselected: () => void,
 * }} DynamicListContract
 */
