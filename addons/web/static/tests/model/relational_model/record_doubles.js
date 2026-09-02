// @ts-check

import { markRaw } from "@odoo/owl";
import { RECORD_CONTRACT_SURFACE } from "@web/model/relational_model/record_contract";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { RecordSaveCoordinator } from "@web/model/relational_model/record_save_coordinator";

export { RECORD_CONTRACT_SURFACE };

/**
 * @typedef {{
 * data: Record<string, any>,
 * savedData: Record<string, any>,
 * _values: Record<string, any>,
 * _editState: import("@web/model/relational_model/record_edit_state").RecordEditState,
 * _hasChanges: boolean,
 * changes: Record<string, any>,
 * _textValues: Record<string, any>,
 * _initialTextValues: Record<string, any>,
 * setEvalContext: () => void,
 * _clearChanges: () => void,
 * rebuildData: () => void,
 * }} RecordStateSurface
 */

/**
 * @param {Record<string, any>} target
 * @param {{ changes?: Record<string, any>, textValues?: Record<string, any>,
 * initialTextValues?: Record<string, any>, dirty?: boolean }} [seed]
 * @returns {Record<string, any>}
 */
export function installEditState(target, seed = {}) {
    const editState = new RecordEditState();
    editState.changes = { ...(seed.changes ?? target.changes ?? {}) };
    editState.textValues = markRaw({
        ...(seed.textValues ?? target._textValues ?? {}),
    });
    editState.initialTextValues = markRaw({
        ...(seed.initialTextValues ?? seed.textValues ?? target._textValues ?? {}),
    });
    editState.dirty = seed.dirty ?? target.dirty ?? false;
    Object.defineProperties(target, {
        _editState: { value: editState, writable: true },
        changes: {
            get: () => editState.changes,
            set: (v) => {
                editState.changes = v;
            },
            configurable: true,
        },
        _textValues: {
            get: () => editState.textValues,
            set: (v) => {
                editState.textValues = v;
            },
            configurable: true,
        },
        _initialTextValues: {
            get: () => editState.initialTextValues,
            set: (v) => {
                editState.initialTextValues = v;
            },
            configurable: true,
        },
        dirty: {
            get: () => editState.dirty,
            set: (v) => {
                editState.dirty = v;
            },
            configurable: true,
        },
    });
    return target;
}

export const RECORD_STATE_TRANSITIONS = {
    /** @this {RecordStateSurface} */
    rebuildData() {
        this.data = { ...this._values, ...this.changes };
        this.setEvalContext();
    },
    /**
     * @this {RecordStateSurface}
     * @param {Record<string, any>} [extraValues]
     */
    commitChanges(extraValues) {
        this._values = { ...this._values, ...this.changes, ...extraValues };
        this._editState.commit();
        this.rebuildData();
    },
    /** @this {RecordStateSurface} */
    discardChanges() {
        this._editState.rollback();
        this.rebuildData();
    },
    /**
     * @this {RecordStateSurface}
     * @param {Record<string, any>} values
     */
    resetValues(values) {
        this._values = values;
        this._editState.reset();
        this.rebuildData();
    },
};

/**
 * @param {Object} [opts]
 * @param {Record<string, any>} [opts.changes]
 * @param {Record<string, any>} [opts.textValues]
 * @param {Record<string, any>} [opts.initialTextValues]
 * @param {Record<string, any>} [opts.values]
 * @param {Record<string, any>} [opts.data]
 * @param {string[]} [opts.invalidFields]
 * @param {string[]} [opts.unsetRequiredFields]
 * @param {boolean} [opts.dirty]
 * @param {boolean} [opts.isNew]
 * @param {Record<string, any>} [opts.fields]
 * @param {Record<string, any>} [opts.activeFields]
 * @param {(fieldName: string) => boolean} [opts.isRequired]
 * @param {(fieldName: string) => boolean} [opts.isInvisible]
 * @param {((data: any[], fieldName: string, options?: any) => any) | null} [opts.createStaticListDatapoint]
 * @param {((properties: any, fieldName: string, parent: any, currentValues: any) => any) | null} [opts.processProperties]
 * @returns {any}
 */
export function makeRecordDouble({
    changes = {},
    textValues = {},
    initialTextValues = {},
    values = {},
    data = null,
    invalidFields = [],
    unsetRequiredFields = invalidFields,
    dirty = false,
    isNew = false,
    fields = null,
    activeFields = null,
    isRequired = () => false,
    isInvisible = () => false,
    createStaticListDatapoint = null,
    processProperties = null,
} = {}) {
    const merged = data ?? { ...values, ...changes };
    const typesAreKnown = fields !== null;
    if (fields === null) {
        fields = {};
        for (const key of Object.keys({ ...merged, ...changes })) {
            fields[key] = { type: "char", name: key };
        }
    }
    if (activeFields === null) {
        activeFields = Object.fromEntries(
            Object.keys(fields).map((name) => [name, {}]),
        );
    }

    /** @type {Record<string, any>} */
    const derivedTextValues = {};
    if (typesAreKnown) {
        for (const [fieldName, value] of Object.entries(merged)) {
            if (["char", "text", "html"].includes(fields[fieldName]?.type)) {
                derivedTextValues[fieldName] = value;
            }
        }
    }
    const editState = new RecordEditState();
    editState.changes = { ...changes };
    editState.textValues = markRaw({ ...derivedTextValues, ...textValues });
    editState.initialTextValues = markRaw({
        ...derivedTextValues,
        ...initialTextValues,
    });
    editState.invalidFields = new Set(invalidFields);
    for (const fieldName of unsetRequiredFields) {
        editState.unsetRequiredFields.add(fieldName);
    }
    editState.dirty = dirty;

    return {
        _editState: editState,
        isNew,
        fields,
        activeFields,
        data: merged,
        get savedData() {
            return this._values;
        },
        _values: { ...values },

        get _savePoint() {
            return editState.savePoint;
        },
        set _savePoint(value) {
            editState.savePoint = value;
        },

        get dirty() {
            return editState.dirty;
        },
        set dirty(value) {
            editState.dirty = value;
        },
        get hasPendingChanges() {
            return editState.hasPendingChanges;
        },
        get _hasChanges() {
            return !editState.isChangeSetEmpty;
        },
        snapshotEditState() {
            editState.snapshot();
        },
        restoreEditState() {
            return editState.restoreSnapshot();
        },
        get changes() {
            return editState.changes;
        },
        set changes(value) {
            editState.changes = value;
        },
        get _textValues() {
            return editState.textValues;
        },
        set _textValues(value) {
            editState.textValues = value;
        },
        get _initialTextValues() {
            return editState.initialTextValues;
        },
        set _initialTextValues(value) {
            editState.initialTextValues = value;
        },
        get invalidFields() {
            return editState.invalidFields;
        },
        set invalidFields(value) {
            editState.invalidFields = value;
        },
        get unsetRequiredFields() {
            return editState.unsetRequiredFields;
        },

        loadedFieldNames: new Set(Object.keys(merged)),

        ...RECORD_STATE_TRANSITIONS,
        saveState: new RecordSaveCoordinator(),
        _clearChanges: () => editState.clearChanges(),
        clearValidity: () => editState.clearValidity(),
        isFieldRequired: isRequired,
        isFieldInvisible: isInvisible,
        processProperties:
            processProperties ??
            (() => {
                throw new Error(
                    "makeRecordDouble: processProperties is not modelled; " +
                        "pass `processProperties` if the code under test needs it",
                );
            }),
        createStaticListDatapoint:
            createStaticListDatapoint ??
            (() => {
                throw new Error(
                    "makeRecordDouble: createStaticListDatapoint is not modelled; " +
                        "pass `createStaticListDatapoint` if the code under test needs it",
                );
            }),
        setEvalContext: () => {},
        restoreActiveFields: () => {},
        setInvalidFieldsNotification: (/** @type {() => void} */ close) => {
            editState.closeInvalidFieldsNotification = close;
        },
        closeInvalidFieldsNotification: () => {
            editState.closeInvalidFieldsNotification();
            editState.closeInvalidFieldsNotification = () => {};
        },
        checkValidityLocked: () => true,
    };
}
