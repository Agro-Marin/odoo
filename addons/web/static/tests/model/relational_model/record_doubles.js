// @ts-check

/**
 * Test doubles for the model layer's DOM-free unit tests.
 *
 * The ``relational_model/`` helpers (``record_savepoint``, ``record_validator``,
 * ``record_save``, …) take a ``RelationalRecord`` as first argument and reach
 * into its ``_``-prefixed surface. That surface is a real contract, but it is
 * only declared by the class — so every hand-rolled mock in the test suite has
 * to re-implement it, and every extension of it silently breaks all of them at
 * once (adding ``_unsetRequiredFields`` to the savepoint broke 30 tests).
 *
 * {@link makeRecordDouble} is the single place that models it. The editable
 * state is a REAL {@link RecordEditState} behind the same accessors
 * ``RelationalRecord`` exposes, so the double tracks the contract instead of
 * approximating it: a change to the invariants shows up as a test failure in
 * the code under test, not as a mock that quietly disagrees.
 */

import { markRaw } from "@odoo/owl";
import { RECORD_CONTRACT_SURFACE } from "@web/model/relational_model/record_contract";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { RecordSaveCoordinator } from "@web/model/relational_model/record_save_coordinator";

// The contract now lives in production, beside the class it describes; the
// doubles are a consumer of it, not its owner. Re-exported so the suites that
// import it from here keep working.
export { RECORD_CONTRACT_SURFACE };

/**
 * The record-level state transitions the model helpers now call. Expressed
 * against the plain `_values`/`_changes`/`_textValues` surface so doubles that
 * build their own record shape can spread it, instead of each re-deriving the
 * (order-sensitive) sequence.
 */
/**
 * @typedef {{
 *  data: Record<string, any>,
 *  _values: Record<string, any>,
 *  _changes: Record<string, any>,
 *  _textValues: Record<string, any>,
 *  _initialTextValues: Record<string, any>,
 *  _setEvalContext: () => void,
 *  _clearChanges: () => void,
 *  _rebuildData: () => void,
 * }} RecordStateSurface
 */

export const RECORD_STATE_TRANSITIONS = {
    /** @this {RecordStateSurface} */
    _rebuildData() {
        this.data = { ...this._values, ...this._changes };
        this._setEvalContext();
    },
    /**
     * @this {RecordStateSurface}
     * @param {Record<string, any>} [extraValues]
     */
    _commitChanges(extraValues) {
        this._values = { ...this._values, ...this._changes, ...extraValues };
        this._clearChanges();
        this._initialTextValues = { ...this._textValues };
        this._rebuildData();
    },
    /** @this {RecordStateSurface} */
    _discardChanges() {
        this._clearChanges();
        this._textValues = { ...this._initialTextValues };
        this._rebuildData();
    },
    /**
     * @this {RecordStateSurface}
     * @param {Record<string, any>} values
     */
    _resetValues(values) {
        this._values = values;
        this._clearChanges();
        this._textValues = {};
        this._initialTextValues = {};
        this._rebuildData();
    },
};

/**
 * @param {Object} [opts]
 * @param {Record<string, any>} [opts.changes] pending edits
 * @param {Record<string, any>} [opts.textValues]
 * @param {Record<string, any>} [opts.initialTextValues]
 * @param {Record<string, any>} [opts.values] server-confirmed values
 * @param {Record<string, any>} [opts.data] merged view (defaults to values+changes)
 * @param {string[]} [opts.invalidFields]
 * @param {string[]} [opts.unsetRequiredFields] defaults to ``invalidFields``
 * @param {boolean} [opts.dirty]
 * @param {boolean} [opts.isNew]
 * @param {Record<string, any>} [opts.fields] field defs (inferred as char when omitted)
 * @param {Record<string, any>} [opts.activeFields] defaults to one entry per field
 * @param {(fieldName: string) => boolean} [opts.isRequired]
 * @param {(fieldName: string) => boolean} [opts.isInvisible]
 * @param {((data: any[], fieldName: string, options?: any) => any) | null} [opts.createStaticListDatapoint]
 *        the contract member this double cannot fake; throws unless supplied
 * @param {((properties: any, fieldName: string, parent: any, currentValues: any) => any) | null} [opts.processProperties]
 *        the properties-processing seam; throws unless supplied
 * @returns {any} a record-shaped double
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

    const editState = new RecordEditState();
    editState.changes = { ...changes };
    editState.textValues = markRaw({ ...textValues });
    editState.initialTextValues = markRaw({ ...initialTextValues });
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
        _values: { ...values },

        // `RelationalRecord` delegates this to the edit state; a plain property
        // here would let a double disagree with the class it stands in for.
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
        get _changes() {
            return editState.changes;
        },
        set _changes(value) {
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
        get _invalidFields() {
            return editState.invalidFields;
        },
        set _invalidFields(value) {
            editState.invalidFields = value;
        },
        get _unsetRequiredFields() {
            return editState.unsetRequiredFields;
        },

        // The list-facing half of the contract. `StaticList._getResIdsToLoad`
        // asks a cached record which fields it already holds, to decide whether
        // a row still needs a webRead; a double without it makes that question
        // throw rather than answer.
        _loadedFieldNames: new Set(Object.keys(merged)),

        ...RECORD_STATE_TRANSITIONS,
        saveState: new RecordSaveCoordinator(),
        _clearChanges: () => editState.clearChanges(),
        _clearValidity: () => editState.clearValidity(),
        _isRequired: isRequired,
        _isInvisible: isInvisible,
        // Part of the contract, but building a real StaticList is beyond what a
        // DOM-free double should fake. Throwing says "not modelled here" rather
        // than handing back an approximation a test could quietly believe.
        // The seam two suites stub to test value transformation in isolation.
        // Defaulting to the real `processProperties` would silently un-isolate
        // any test that forgot to pass one.
        _processProperties:
            processProperties ??
            (() => {
                throw new Error(
                    "makeRecordDouble: _processProperties is not modelled; " +
                        "pass `processProperties` if the code under test needs it",
                );
            }),
        _createStaticListDatapoint:
            createStaticListDatapoint ??
            (() => {
                throw new Error(
                    "makeRecordDouble: _createStaticListDatapoint is not modelled; " +
                        "pass `createStaticListDatapoint` if the code under test needs it",
                );
            }),
        _setEvalContext: () => {},
        _restoreActiveFields: () => {},
        setInvalidFieldsNotification: (close) => {
            editState.closeInvalidFieldsNotification = close;
        },
        closeInvalidFieldsNotification: () => {
            editState.closeInvalidFieldsNotification();
            editState.closeInvalidFieldsNotification = () => {};
        },
        _checkValidity: () => true,
    };
}
