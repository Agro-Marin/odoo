// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_contract */

/**
 * The record surface the `relational_model/` helpers and `StaticList` reach for.
 *
 * `RelationalRecord` was decomposed into satellites (`record_save`,
 * `record_savepoint`, `record_validator`, …) that take the record and reach into
 * its `_`-prefixed members. That is a real interface — the satellites are
 * separately unit-testable precisely because it exists — but it was declared
 * only by the class, so nothing could state which members are the contract and
 * which are internals that happen to be reachable.
 *
 * This list is that statement. It lived in `static/tests/.../record_doubles.js`,
 * where it was already load-bearing: every hand-rolled mock had to re-implement
 * the surface, and extending it broke them all at once (adding
 * `_unsetRequiredFields` to the savepoint broke thirty tests; a fixture omitting
 * `_loadedFieldNames` made `_getResIdsToLoad` throw instead of answering).
 * Keeping the declaration in the test tree meant production code could not refer
 * to the contract it was actually programming against.
 *
 * It is deliberately NOT the set of members satellites reach today. Fifteen of
 * the thirty-five privates read from outside `record.js` are named here; the
 * other twenty are undeclared reaches, and each one is a decision to take —
 * promote it here, or narrow it away. Adding an entry is that decision, made
 * once and reviewably, in one file.
 *
 * Both directions of drift fail loudly in
 * `record_doubles_conformance.test.js`: a REAL `RelationalRecord` must carry
 * every entry (so renaming one in the class breaks this list rather than
 * silently orphaning it), `makeRecordDouble` must carry them too (so the double
 * cannot fall behind), and the double may not invent members the record lacks.
 *
 * @type {string[]}
 */
export const RECORD_CONTRACT_SURFACE = [
    // identity + shape
    "activeFields",
    "data",
    "fields",
    "isNew",
    // editable state
    "_changes",
    "_initialTextValues",
    "_invalidFields",
    "_savePoint",
    "_textValues",
    "_unsetRequiredFields",
    "_values",
    "dirty",
    "hasPendingChanges",
    // The edit state itself, not just the accessors over it. `record_savepoint`
    // snapshots and restores it; routing that through new `_snapshot()` /
    // `_restoreSnapshot()` delegators on the record would add exactly the hops
    // this contract exists to remove.
    "_editState",
    // list-facing
    "_loadedFieldNames",
    // behaviour the helpers invoke
    "_checkValidity",
    "_clearChanges",
    "_clearValidity",
    "_commitChanges",
    "_createStaticListDatapoint",
    "_discardChanges",
    "_isInvisible",
    "_isRequired",
    // A one-line forward to `processProperties`, and by F9's rule a hop to
    // delete. It is not: two suites build a fake record with
    // `_processProperties` stubbed, to test value transformation in isolation
    // from properties processing. The hop is a TEST SEAM, and routing the two
    // call sites at the import instead would delete that seam to improve a
    // metric — the same trade refused for `record_savepoint`.
    "_processProperties",
    "_rebuildData",
    "_resetValues",
    "_restoreActiveFields",
    "_setEvalContext",
    "closeInvalidFieldsNotification",
];

/**
 * What an OWNING list or model invokes on a record it holds.
 *
 * A second audience, and the reason this file has two arrays the way
 * `static_list_contract.js` does. `RECORD_CONTRACT_SURFACE` above is what
 * `Record`'s OWN helpers reach — the sideways surface left by decomposing the
 * class. This is the downward one: `StaticList` calling `record._applyValues()`
 * on a row it is loading, `RelationalModel` calling `record._setData()`,
 * `dynamic_list` calling `editedRecord._save()`. The caller owns the callee, and
 * these are the operations ownership consists of.
 *
 * Keeping them apart matters because the two surfaces answer different
 * questions. Widen the first and a helper extracted from `Record` may see more
 * of it; widen this one and every list in the tree may. A member appearing in
 * both would mean the distinction had collapsed, which the agreement test
 * refuses.
 *
 * @type {string[]}
 */
export const RECORD_OWNER_SURFACE = [
    "_applyChanges",
    "_applyDefaultValues",
    "_applyValues",
    "_displayInvalidFieldNotification",
    "_getChanges",
    "_getDefaultValues",
    "_isReadonly",
    "_manuallyAdded",
    "_parseServerValues",
    "_save",
    "_setData",
    "_switchMode",
    "_update",
    "_virtualId",
];

/**
 * The owner-facing surface as a type.
 *
 * `RECORD_OWNER_SURFACE` and this typedef must name the same members.
 *
 * @typedef {{
 *  _applyChanges: (changes: Record<string, any>, options?: any) => any,
 *  _applyDefaultValues: (values?: Record<string, any>) => any,
 *  _applyValues: (values: Record<string, any>) => any,
 *  _displayInvalidFieldNotification: () => void,
 *  _getChanges: (options?: any) => Record<string, any>,
 *  _getDefaultValues: () => Record<string, any>,
 *  _isReadonly: (fieldName: string) => boolean,
 *  _manuallyAdded: boolean,
 *  _parseServerValues: (values: Record<string, any>, current?: any) => Record<string, any>,
 *  _save: (options?: any) => Promise<any>,
 *  _setData: (data: Record<string, any>) => void,
 *  _switchMode: (mode: string) => Promise<any> | void,
 *  _update: (changes: Record<string, any>, options?: any) => Promise<any>,
 *  _virtualId: string | false,
 * }} RecordOwnerContract
 */

/**
 * The same surface as a type, for satellites to declare in place of the whole
 * `RelationalRecord`. A satellite annotated `RecordContract` that reaches past
 * this list is a typecheck failure rather than an invisible entry in the
 * cross-module private-access budget.
 *
 * `RECORD_CONTRACT_SURFACE` above and this typedef must name the same members;
 * they are checked against each other in
 * `record_doubles_conformance.test.js`.
 *
 * @typedef {{
 *  activeFields: Record<string, any>,
 *  data: Record<string, any>,
 *  fields: Record<string, any>,
 *  isNew: boolean,
 *  _changes: Record<string, any>,
 *  _initialTextValues: Record<string, any>,
 *  _invalidFields: Set<string>,
 *  _savePoint: Record<string, any> | undefined,
 *  _textValues: Record<string, any>,
 *  _unsetRequiredFields: Set<string>,
 *  _values: Record<string, any>,
 *  dirty: boolean,
 *  hasPendingChanges: boolean,
 *  _editState: import("./record_edit_state").RecordEditState,
 *  _loadedFieldNames: Set<string>,
 *  _checkValidity: (options?: any) => boolean,
 *  _clearChanges: () => void,
 *  _clearValidity: () => void,
 *  _commitChanges: (extraValues?: Record<string, any>) => void,
 *  _createStaticListDatapoint: (data: any[], fieldName: string, options?: { orderBys?: Record<string, any> }) => any,
 *  _discardChanges: () => void,
 *  _isInvisible: (fieldName: string) => boolean,
 *  _isRequired: (fieldName: string) => boolean,
 *  _processProperties: (properties: any, fieldName: string, parent: any, currentValues: any) => Record<string, any>,
 *  _rebuildData: () => void,
 *  _resetValues: (values: Record<string, any>) => void,
 *  _restoreActiveFields: () => void,
 *  _setEvalContext: () => void,
 *  closeInvalidFieldsNotification: () => void,
 * }} RecordContract
 */
