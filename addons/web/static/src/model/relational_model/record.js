// @ts-check
/** @odoo-module native */

import { markRaw, toRaw } from "@odoo/owl";
import { isX2Many } from "@web/core/field_types";
import { omit } from "@web/core/utils/collections/objects";
import { Operation } from "@web/core/utils/operation";

import { DataPoint } from "./datapoint.js";
import { getBasicEvalContext, getFieldContext } from "./field_context.js";
import { RecordEditState } from "./record_edit_state.js";
import {
    archive,
    deleteRecord,
    duplicateRecord,
    unarchive,
} from "./record_lifecycle.js";
import {
    preprocessHtmlChanges,
    preprocessMany2oneChanges,
    preprocessMany2OneReferenceChanges,
    preprocessPropertiesChanges,
    preprocessReferenceChanges,
    preprocessX2manyChanges,
} from "./record_preprocessors.js";
import { processProperties } from "./record_properties.js";
import { save } from "./record_save.js";
import { RecordSaveCoordinator } from "./record_save_coordinator.js";
import { addSavePoint, discard } from "./record_savepoint.js";
import {
    computeChangeset,
    computeRevalidationScope,
    isFieldInvisible,
    isFieldReadonly,
    isFieldRequired,
} from "./record_utils.js";
import {
    checkValidity,
    displayInvalidFieldNotification,
    removeInvalidFields,
    resetFieldValidity,
    setInvalidField,
} from "./record_validator.js";
import {
    computeDataContext,
    formatServerValue,
    getDefaultValues,
    getTextValues,
    parseServerValues,
} from "./record_value_transforms.js";

/**
 * @template {keyof any} K
 * @template T
 * @typedef {{ [P in K]: T }} RecordType
 */

/**
 * @typedef {{
 * currentValues?: RecordType<string, unknown>;
 * orderBys?: RecordType<string, unknown>;
 * withInvisible?: boolean;
 * withReadonly?: boolean;
 * keepChanges?: boolean;
 * }} FieldSpecifications
 * @typedef {"edit" | "readonly"} Mode
 */

const NO_UNDO = () => {};

const MULTI_EDIT_RESULT = Symbol("multiEditResult");

/**
 * `_update` answers a multi-edit dispatch with a sentinel-keyed envelope, so
 * that the caller can tell "the edit was handed to the multi-save path, which
 * answered X" from "the edit was applied here and there is nothing to report".
 *
 * Both exits of `update` have to open it. Leaking the envelope makes a caller
 * that tests the result for truthiness -- `DynamicGroupList.moveRecord` does,
 * to decide whether to revert a drag -- read a refused multi-save as a
 * successful one, because the envelope is an object and `false` is not.
 *
 * @param {any} dispatched
 * @returns {{ dispatched: boolean, result: any }}
 */
function openMultiEditEnvelope(dispatched) {
    if (dispatched && MULTI_EDIT_RESULT in dispatched) {
        return { dispatched: true, result: dispatched[MULTI_EDIT_RESULT] };
    }
    return { dispatched: false, result: undefined };
}

export class RelationalRecord extends DataPoint {
    static type = "Record";

    /**
     * @type {typeof DataPoint.prototype.setup<{
     * manuallyAdded?: boolean;
     * onUpdate?: (params?: { withoutParentUpdate?: boolean }) => any;
     * parentRecord?: RelationalRecord;
     * virtualId?: string;
     * }>}
     */
    setup(_config, data, options = {}) {
        this._manuallyAdded = options.manuallyAdded === true;
        this._onUpdate = options.onUpdate || (() => {});
        this._parentRecord = options.parentRecord;
        this.canSaveOnUpdate = !options.parentRecord;
        this._virtualId = options.virtualId || false;
        this._isEvalContextReady = false;

        this._editState = new RecordEditState();

        this.selected = false;
        /** @type {RecordSaveCoordinator} */
        this.saveState = markRaw(new RecordSaveCoordinator());

        const parentRecord = this._parentRecord;
        if (parentRecord) {
            this.evalContext = {
                get parent() {
                    return parentRecord.evalContext;
                },
            };
            this.evalContextWithVirtualIds = {
                get parent() {
                    return parentRecord.evalContextWithVirtualIds;
                },
            };
        } else {
            this.evalContext = {};
            this.evalContextWithVirtualIds = {};
        }
        /** @type {Set<string>} */
        this._loadedFieldNames = markRaw(new Set(Object.keys(data)));
        const missingFields = this.fieldNames.filter(
            (fieldName) => !(fieldName in data),
        );
        data = { ...this._getDefaultValues(missingFields), ...data };
        this._setData(data);
    }

    /**
     * @param {Record<string, any>} data
     * @param {FieldSpecifications} [params]
     */
    _setData(data, { orderBys, keepChanges } = {}) {
        this._isEvalContextReady = false;
        if (this.data) {
            for (const fieldName of Object.keys(data)) {
                this._loadedFieldNames.add(fieldName);
            }
        }
        if (this.resId) {
            this._values = markRaw(this._parseServerValues(data, { orderBys }));
            Object.assign(this._textValues, this._getTextValues(data));
        } else {
            const allVals = { ...this._getDefaultValues(), ...data };
            this._values = markRaw(this._parseServerValues(allVals, { orderBys }));
            Object.assign(this._textValues, this._getTextValues(allVals));
        }
        for (const fieldName of Object.keys(this._textValues)) {
            if (!(fieldName in this._values)) {
                delete this._textValues[fieldName];
            }
        }
        if (!keepChanges) {
            this._clearChanges();
        } else {
            this.dirty = this.dirty || this._hasChanges;
        }
        this.data = { ...this._values, ...this._changes };
        this._initialTextValues = markRaw({ ...this._textValues });
        if (keepChanges) {
            Object.assign(this._textValues, this._getTextValues(this._changes));
        }
        this._setEvalContext();

        if (!keepChanges) {
            this._clearValidity();
            this._savePoint = undefined;
        }
        if (!this.isNew && this.isInEdition && !this._parentRecord) {
            this._checkValidity();
        }
    }

    get canBeAbandoned() {
        return this.isNew && !this.dirty && this._manuallyAdded;
    }

    get hasData() {
        return true;
    }

    /** @type {boolean} */
    get isActive() {
        if ("active" in this.activeFields) {
            return this.data.active;
        } else if ("x_active" in this.activeFields) {
            return this.data.x_active;
        }
        return true;
    }

    get isInEdition() {
        if (this.config.mode === "readonly") {
            return false;
        } else {
            return this.config.mode === "edit" || !this.resId;
        }
    }

    get isNew() {
        return !this.resId;
    }

    get isValid() {
        return !this._invalidFields.size;
    }

    get resId() {
        return this.config.resId;
    }

    get resIds() {
        return this.config.resIds;
    }

    /**
     * @returns {boolean}
     */
    get skipsParentUpdate() {
        return this._noUpdateParent;
    }

    archive(/** @type {any} */ reload) {
        return this.model.mutex.exec(() => archive(this, reload));
    }

    /** @param {{ displayNotification?: boolean }} [options] */
    async checkValidity({ displayNotification } = {}) {
        await this.model.urgentSave.awaitUnlessUrgent(this.model._askChanges());
        if (this.model.urgentSave.isActive) {
            return this._checkValidity({ displayNotification });
        }
        return this.model.mutex.exec(() =>
            this._checkValidity({ displayNotification }),
        );
    }

    /**
     * @param {() => void} close
     * @returns {void}
     */
    setInvalidFieldsNotification(close) {
        this._editState.closeInvalidFieldsNotification = close;
    }

    /**
     * @returns {void}
     */
    closeInvalidFieldsNotification() {
        this._editState.closeInvalidFieldsNotification();
        this._editState.closeInvalidFieldsNotification = () => {};
    }

    /**
     * @param {Record<string, any>} activeFieldsToRestore
     * @returns {void}
     */
    extendActiveFields(activeFieldsToRestore) {
        this._noUpdateParent = true;
        this._activeFieldsToRestore = { ...activeFieldsToRestore };
    }

    /**
     * @param {number} resId
     * @returns {void}
     */
    assignResId(resId) {
        this.model._patchConfig(this.config, { resId, resIds: [resId] });
        this._virtualId = false;
    }

    delete() {
        return this.model.mutex.exec(() => deleteRecord(this));
    }

    async discard() {
        this.model.closeUrgentSaveNotification();
        await this.model._askChanges();
        return this.model.mutex.exec(() => this._discard());
    }

    duplicate() {
        return this.model.mutex.exec(() => duplicateRecord(this));
    }

    /**
     * @param {FieldSpecifications} [params]
     */
    async getChanges({ withReadonly } = {}) {
        await this.model._askChanges();
        return this.model.mutex.exec(() =>
            this._getChanges(this._changes, { withReadonly }),
        );
    }

    async isDirty() {
        await this.model._askChanges();
        return this.dirty;
    }

    /**
     * @param {string} fieldName
     */
    isFieldInvalid(fieldName) {
        return this._invalidFields.has(fieldName);
    }

    load() {
        if (arguments.length) {
            throw new Error("Record.load() does not accept arguments");
        }
        return this.model.mutex.exec(() => this._load());
    }

    /**
     * @param {Parameters<RelationalRecord["_save"]>[0]} [options]
     */
    async save(options) {
        await this.model._askChanges();
        return this.model.mutex.exec(() => this._save(options));
    }

    /**
     * @param {string} fieldName
     */
    async setInvalidField(fieldName) {
        this._markDirty();
        return this._setInvalidField(fieldName);
    }

    /**
     * @param {string} fieldName
     */
    async resetFieldValidity(fieldName) {
        return this._resetFieldValidity(fieldName);
    }

    /**
     * @param {Mode} mode
     */
    switchMode(mode) {
        return this.model.mutex.exec(() => this._switchMode(mode));
    }

    toggleSelection(/** @type {any} */ selected) {
        return this.model.mutex.exec(() => {
            this._toggleSelection(selected);
        });
    }

    unarchive(/** @type {any} */ reload) {
        return this.model.mutex.exec(() => unarchive(this, reload));
    }

    /**
     * @param {Object} changes
     * @param {{ save?: boolean, withoutParentUpdate?: boolean }} [options]
     */
    async update(changes, { save, withoutParentUpdate } = {}) {
        if (this.model.urgentSave.isActive) {
            const envelope = await this._update(changes, { withoutParentUpdate });
            return openMultiEditEnvelope(envelope).result;
        }
        return this.model.mutex.exec(async () => {
            const envelope = await this._update(changes, {
                withoutOnchange: save,
                withoutParentUpdate,
            });
            const { dispatched, result } = openMultiEditEnvelope(envelope);
            if (dispatched) {
                return result;
            }
            if (save && this.canSaveOnUpdate) {
                return this._save();
            }
        });
    }

    urgentSave() {
        if (toRaw(this).saveState.isInFlight) {
            return true;
        }
        return this.model.urgentSave.run(() => this._save({ reload: false }));
    }

    /** @returns {boolean} */
    get hasPendingChanges() {
        return this._editState.hasPendingChanges;
    }

    /**
     * Whether an edit is staged, ignoring the `dirty` flag -- which can be set
     * by a field that reported itself invalid without producing a value.
     *
     * @returns {boolean}
     */
    get _hasChanges() {
        return !this._editState.isChangeSetEmpty;
    }

    /**
     * The values the server last returned, with no pending edit applied.
     *
     * `data` is this overlaid with `_changes`, so the pair answers "what did
     * this field hold before the user touched it?" -- a question consumers
     * outside the model have, and used to answer by reading `_values` and
     * `_changes` directly across a tree boundary. Those are this record's
     * bookkeeping and its collaborators'; this is the public half.
     *
     * @returns {Record<string, any>}
     */
    get savedData() {
        return this._values;
    }

    /** @returns {boolean} */
    get dirty() {
        return this._editState.dirty;
    }

    set dirty(value) {
        this._editState.dirty = value;
    }

    /**
     * @returns {Record<string, any>}
     */
    get _changes() {
        return this._editState.changes;
    }

    set _changes(initial) {
        this._editState.changes = initial;
    }

    /** @returns {Set<string>} */
    get _invalidFields() {
        return this._editState.invalidFields;
    }

    set _invalidFields(value) {
        this._editState.invalidFields = value;
    }

    /** @returns {Set<string>} */
    get _unsetRequiredFields() {
        return this._editState.unsetRequiredFields;
    }

    /** @returns {Record<string, any>} */
    get _textValues() {
        return this._editState.textValues;
    }

    set _textValues(value) {
        this._editState.textValues = value;
    }

    /** @returns {Record<string, any>} */
    get _initialTextValues() {
        return this._editState.initialTextValues;
    }

    set _initialTextValues(value) {
        this._editState.initialTextValues = value;
    }

    /** @returns {any} */
    get _savePoint() {
        return this._editState.savePoint;
    }

    set _savePoint(value) {
        this._editState.savePoint = value;
    }

    _clearChanges() {
        this._editState.clearChanges();
    }

    _rebuildData() {
        this.data = { ...this._values, ...this._changes };
        this._setEvalContext();
    }

    /**
     * @param {Record<string, any>} [extraValues]
     */
    _commitChanges(extraValues) {
        this._values = markRaw({
            ...this._values,
            ...this._changes,
            ...extraValues,
        });
        this._editState.commit();
        this._rebuildData();
    }

    _discardChanges() {
        this._editState.rollback();
        this._rebuildData();
    }

    /**
     * @param {Record<string, any>} values
     */
    _resetValues(values) {
        this._values = markRaw(values);
        this._editState.reset();
        this._rebuildData();
    }

    _clearValidity() {
        this._editState.clearValidity();
    }

    _markDirty() {
        this._editState.markDirty();
    }

    _addSavePoint() {
        addSavePoint(this);
    }

    /**
     * `_editState` is this record's own field, so the two collaborators that
     * need to take and put back an edit-state snapshot ask for the behaviour
     * rather than reaching for the object. The record is the face; nothing
     * outside it names `_editState`.
     *
     * @returns {void}
     */
    _snapshotEditState() {
        this._editState.snapshot();
    }

    /**
     * @returns {boolean} whether a snapshot was there to restore
     */
    _restoreEditState() {
        return this._editState.restoreSnapshot();
    }

    /** @param {any} changes */
    _applyChanges(changes, serverChanges = {}, { undoable = false } = {}) {
        let undoChanges = NO_UNDO;
        if (undoable) {
            const initialTextValues = { ...this._textValues };
            const initialChanges = { ...this._changes };
            const initialData = { ...toRaw(this.data) };
            const initialDirty = this.dirty;
            const invalidFields = [...toRaw(this._invalidFields)];
            const unsetRequiredFields = [...toRaw(this._unsetRequiredFields)];
            const listSnapshots = [];
            for (const fieldName of new Set([
                ...Object.keys(changes),
                ...Object.keys(serverChanges),
            ])) {
                const value = toRaw(this.data)[fieldName];
                if (isX2Many(this.fields[fieldName]) && value?._commands) {
                    listSnapshots.push({ list: value, snapshot: value._snapshot() });
                }
            }
            undoChanges = () => {
                for (const fieldName of invalidFields) {
                    this._setInvalidFieldFlag(fieldName);
                }
                for (const fieldName of unsetRequiredFields) {
                    this._unsetRequiredFields.add(fieldName);
                }
                for (const fieldName of Object.keys(toRaw(this.data))) {
                    if (!(fieldName in initialData)) {
                        delete this.data[fieldName];
                    }
                }
                Object.assign(this.data, initialData);
                for (const { list, snapshot } of listSnapshots) {
                    list._restore(snapshot);
                }
                this._changes = markRaw(initialChanges);
                Object.assign(this._textValues, initialTextValues);
                this.dirty = initialDirty;
                this._setEvalContext();
            };
        }

        for (const fieldName of Object.keys(changes)) {
            let change = changes[fieldName];
            if (change instanceof Operation) {
                change = change.compute(this.data[fieldName]);
            }
            this._changes[fieldName] = change;
            this.data[fieldName] = change;
            if (this.fields[fieldName].type === "html") {
                this._textValues[fieldName] =
                    change === false ? false : change.toString();
            } else if (["char", "text"].includes(this.fields[fieldName].type)) {
                this._textValues[fieldName] = change;
            }
        }

        const parsedChanges = this._parseServerValues(serverChanges, {
            currentValues: this.data,
        });
        for (const fieldName of Object.keys(parsedChanges)) {
            this._changes[fieldName] = parsedChanges[fieldName];
            this.data[fieldName] = parsedChanges[fieldName];
        }
        Object.assign(this._textValues, this._getTextValues(serverChanges));

        this._setEvalContext();

        const changedFieldNames = [
            ...Object.keys(changes),
            ...Object.keys(serverChanges),
        ];
        this._removeInvalidFields(...changedFieldNames);
        const scopedFields = computeRevalidationScope(
            changedFieldNames,
            this.activeFields,
        );
        this._checkValidity({ removeInvalidOnly: true, scopedFields });
        return undoChanges;
    }

    _applyDefaultValues() {
        const fieldNames = this.fieldNames.filter(
            (fieldName) => !(fieldName in this.data),
        );
        const defaultValues = this._getDefaultValues(fieldNames);
        if (this.isNew) {
            this._applyChanges({}, defaultValues);
        } else {
            this._applyValues(defaultValues);
        }
    }

    _applyValues(/** @type {any} */ values) {
        const x2manyMerges = [];
        for (const fieldName of Object.keys(values)) {
            const field = this.fields[fieldName];
            if (isX2Many(field) && this._changes[fieldName]?._commands?.length) {
                x2manyMerges.push(fieldName);
            }
        }
        const newValues = this._parseServerValues(
            x2manyMerges.length ? omit(values, ...x2manyMerges) : values,
        );
        for (const fieldName of x2manyMerges) {
            const list = this._changes[fieldName];
            list._applyServerValues(values[fieldName]);
            newValues[fieldName] = list;
        }
        Object.assign(this._values, newValues);
        for (const fieldName of Object.keys(newValues)) {
            this._loadedFieldNames.add(fieldName);
            if (fieldName in this._changes) {
                if (isX2Many(this.fields[fieldName])) {
                    this._changes[fieldName] = newValues[fieldName];
                }
            }
        }
        Object.assign(this.data, this._values, this._changes);
        const textValues = this._getTextValues(values);
        Object.assign(this._initialTextValues, textValues);
        Object.assign(this._textValues, textValues, this._getTextValues(this._changes));
        this._setEvalContext();
    }

    /**
     * @param {{ silent?: boolean, displayNotification?: boolean, removeInvalidOnly?: boolean, scopedFields?: Set<string> }} [options]
     */
    _checkValidity(options) {
        return checkValidity(this, options);
    }

    /**
     * @returns {{ withVirtualIds: Object, withoutVirtualIds: Object }}
     */
    _computeDataContext() {
        return computeDataContext(
            toRaw(this.data),
            this.fields,
            this._textValues,
            this.resId,
        );
    }

    /**
     * @param {Array<{id: number, [key: string]: any}>} data
     * @param {string} fieldName
     * @param {FieldSpecifications} [params]
     */
    _createStaticListDatapoint(data, fieldName, { orderBys } = {}) {
        const { related, limit, defaultOrderBy } = this.activeFields[fieldName];
        const relatedActiveFields = related?.activeFields || {};
        const config = {
            resModel: this.fields[fieldName].relation,
            activeFields: relatedActiveFields,
            fields: related?.fields || {},
            relationField: this.fields[fieldName].relation_field || false,
            offset: 0,
            resIds: data.map((r) => r.id),
            orderBy: orderBys?.[fieldName] || defaultOrderBy || [],
            limit:
                limit ||
                (Object.keys(relatedActiveFields).length ? Number.MAX_SAFE_INTEGER : 1),
            context: {},
        };
        const options = {
            onUpdate: (
                /** @type {{ withoutOnchange?: boolean }} */ { withoutOnchange } = {},
            ) => this._update({ [fieldName]: [] }, { withoutOnchange }),
            parent: this,
        };
        return new this.model.Class.StaticList(
            this.model,
            /** @type {any} */ (config),
            /** @type {any} */ (data),
            options,
        );
    }

    _discard() {
        return discard(this);
    }

    _displayInvalidFieldNotification() {
        return displayInvalidFieldNotification(this);
    }

    _formatServerValue(/** @type {any} */ fieldType, /** @type {any} */ value) {
        return formatServerValue(fieldType, value);
    }

    /**
     * @param {RecordType<string, unknown>} [changes]
     * @param {FieldSpecifications} [params]
     * @returns {Record<string, any>}
     */
    _getChanges(changes = this._changes, { withReadonly } = {}) {
        return computeChangeset({
            changes,
            values: this._values,
            isNew: !this.resId,
            fields: this.fields,
            activeFields: this.activeFields,
            evalContext: this.evalContextWithVirtualIds,
            options: { withReadonly },
            getCommands: (fieldName, value, wr) =>
                /** @type {import("./static_list").StaticList} */ (value)._getCommands({
                    withReadonly: wr,
                }),
        });
    }

    _getDefaultValues(fieldNames = this.fieldNames) {
        return getDefaultValues(fieldNames, this.fields);
    }

    /**
     * @param {RecordType<string, unknown>} values
     */
    _getTextValues(values) {
        return getTextValues(values, this.activeFields, this.fields);
    }

    /**
     * @param {string} fieldName
     */
    _isInvisible(fieldName) {
        return isFieldInvisible(
            this.activeFields[fieldName],
            this.evalContextWithVirtualIds,
        );
    }

    /**
     * @param {string} fieldName
     */
    _isReadonly(fieldName) {
        return isFieldReadonly(
            this.activeFields[fieldName],
            this.evalContextWithVirtualIds,
        );
    }

    /**
     * @param {string} fieldName
     */
    _isRequired(fieldName) {
        return isFieldRequired(
            this.activeFields[fieldName],
            this.evalContextWithVirtualIds,
        );
    }

    async _load(nextConfig = {}) {
        if ("resId" in nextConfig && this.resId) {
            throw new Error("Cannot change resId of a record");
        }
        await this.model._reloadWithConfig(this.config, nextConfig, {
            commit: (values) => {
                if (this.resId) {
                    this.model._updateSimilarRecords(this, values);
                }
                this._setData(values);
            },
        });
    }

    /**
     * @param {Object[]} properties
     * @param {string} fieldName
     * @param {any} parent
     * @param {Object} [currentValues]
     */
    _processProperties(properties, fieldName, parent, currentValues) {
        return processProperties(this, properties, fieldName, parent, currentValues);
    }

    /**
     * @param {RecordType<string, unknown>} serverValues
     * @param {FieldSpecifications} [options]
     */
    _parseServerValues(serverValues, options) {
        return parseServerValues(this, serverValues, options);
    }

    /**
     * @param {...string} fieldNames
     */
    _removeInvalidFields(...fieldNames) {
        return removeInvalidFields(this, ...fieldNames);
    }

    /**
     * @returns {void}
     */
    _restoreActiveFields() {
        this._noUpdateParent = false;
        if (!this._activeFieldsToRestore) {
            return;
        }
        this.model._patchConfig(this.config, {
            activeFields: { ...this._activeFieldsToRestore },
        });
        this._activeFieldsToRestore = undefined;
    }

    /**
     * @param {{ reload?: boolean, onError?: (e: Error, actions: { discard: () => void, retry: () => any }) => any, nextId?: number }} [options]
     */
    async _save(options) {
        return save(this, options);
    }

    _setEvalContext() {
        const evalContext = getBasicEvalContext(this.config);
        const dataContext = this._computeDataContext();
        Object.assign(this.evalContext, evalContext, dataContext.withoutVirtualIds);
        Object.assign(
            this.evalContextWithVirtualIds,
            evalContext,
            dataContext.withVirtualIds,
        );
        this._isEvalContextReady = true;

        if (!this._parentRecord || this._parentRecord._isEvalContextReady) {
            for (const [fieldName, value] of Object.entries(toRaw(this.data))) {
                if (isX2Many(this.fields[fieldName])) {
                    value._updateContext(getFieldContext(this, fieldName));
                }
            }
        }
    }

    /**
     * @param {string} fieldName
     */
    async _setInvalidField(fieldName) {
        return setInvalidField(this, fieldName);
    }

    /**
     * @param {string} fieldName
     */
    _setInvalidFieldFlag(fieldName) {
        this._invalidFields.add(fieldName);
    }

    _resetFieldValidity(/** @type {any} */ fieldName) {
        return resetFieldValidity(this, fieldName);
    }

    /**
     * @param {Mode} mode
     */
    _switchMode(mode) {
        this.model._patchConfig(this.config, { mode });
        if (mode === "readonly") {
            this._noUpdateParent = false;
            this._clearValidity();
        }
    }

    _toggleSelection(/** @type {any} */ selected) {
        if (typeof selected === "boolean") {
            this.selected = selected;
        } else {
            this.selected = !this.selected;
        }
        if (!this.selected) {
            this.model.root._onRecordDeselected?.();
        }
    }

    /**
     * @param {Record<string, any>} changes
     * @returns {Promise<Record<string, any>>}
     */
    async _getOnchangeValues(changes) {
        const originalChanges = changes;
        for (const fieldName of Object.keys(originalChanges)) {
            if (originalChanges[fieldName] instanceof Operation) {
                if (changes === originalChanges) {
                    changes = { ...originalChanges };
                }
                changes[fieldName] = originalChanges[fieldName].compute(
                    this.data[fieldName],
                );
            }
        }
        const onChangeFields = Object.keys(changes).filter(
            (fieldName) =>
                this.activeFields[fieldName] && this.activeFields[fieldName].onChange,
        );
        if (!onChangeFields.length) {
            return /** @type {Record<string, any>} */ ({});
        }

        const localChanges = this._getChanges(
            { ...this._changes, ...changes },
            { withReadonly: true },
        );
        if (this.config.relationField) {
            const parentRecord = this._parentRecord;
            localChanges[this.config.relationField] = parentRecord._getChanges(
                parentRecord._changes,
                { withReadonly: true },
            );
            if (!this._parentRecord.isNew) {
                localChanges[this.config.relationField].id = this._parentRecord.resId;
            }
        }
        return this.model._onchange(this.config, {
            changes: localChanges,
            fieldNames: onChangeFields,
            evalContext: toRaw(this.evalContext),
            onError: (e) => {
                const undoChanges = this._applyChanges(
                    changes,
                    {},
                    {
                        undoable: true,
                    },
                );
                undoChanges();
                throw e;
            },
        });
    }

    /**
     * @param {Record<string, any>} changes
     * @returns {{ list: any, snapshot: any }[]}
     */
    _snapshotTouchedLists(changes) {
        const listSnapshots = [];
        for (const fieldName of Object.keys(changes)) {
            if (!isX2Many(this.fields[fieldName])) {
                continue;
            }
            const list = toRaw(this.data)[fieldName];
            if (list?._commands) {
                listSnapshots.push({ list, snapshot: list._snapshot() });
            }
        }
        return listSnapshots;
    }

    /**
     * @param {Record<string, any>} changes
     * @returns {Promise<unknown[]>}
     */
    _preprocessChanges(changes) {
        return Promise.all([
            preprocessMany2oneChanges(this, changes),
            preprocessMany2OneReferenceChanges(this, changes),
            preprocessReferenceChanges(this, changes),
            preprocessX2manyChanges(this, changes),
            preprocessPropertiesChanges(this, changes),
            preprocessHtmlChanges(this, changes),
        ]);
    }

    /**
     * @param {Record<string, any>} changes
     * @returns {void}
     */
    _pruneUnchangedMany2ones(changes) {
        for (const fieldName of Object.keys(changes)) {
            if (this.fields[fieldName].type !== "many2one") {
                continue;
            }
            const current = toRaw(this.data[fieldName]);
            const next = changes[fieldName];
            if (
                current &&
                next &&
                current.id === next.id &&
                current.display_name === next.display_name
            ) {
                delete changes[fieldName];
            }
        }
    }

    async _update(
        /** @type {any} */ changes,
        /** @type {{ withoutOnchange?: boolean, withoutParentUpdate?: boolean }} */ {
            withoutOnchange,
            withoutParentUpdate,
        } = {},
    ) {
        changes = { ...changes };
        const raw = toRaw(this);
        const wasDirty = raw.dirty;
        this._markDirty();
        const restoreDirty = () => {
            if (!raw._hasChanges && !raw._invalidFields.size) {
                this.dirty = wasDirty;
            }
        };
        const listSnapshots = this._snapshotTouchedLists(changes);
        const rollbackLists = () => {
            for (const { list, snapshot } of listSnapshots) {
                list._restore(snapshot);
            }
        };

        try {
            await this.model.urgentSave.awaitUnlessUrgent(
                this._preprocessChanges(changes),
            );
        } catch (e) {
            rollbackLists();
            restoreDirty();
            throw e;
        }

        if (this.selected && this.model.multiEdit) {
            let result;
            try {
                result = await this.model.multiEditDispatch(this, changes);
            } catch (e) {
                // Every other failure below unwinds the x2many snapshots taken
                // above; this one used to propagate straight out and leave them
                // applied. `_multiSave` discards the selected records on a
                // rejected save, but not on one from the commands it replays
                // first or from the `onWillSaveMulti` hook.
                rollbackLists();
                restoreDirty();
                throw e;
            }
            restoreDirty();
            return { [MULTI_EDIT_RESULT]: result };
        }

        let onchangeServerValues = {};
        if (!withoutOnchange) {
            try {
                onchangeServerValues =
                    (await this.model.urgentSave.unlessUrgent(() =>
                        this._getOnchangeValues(changes),
                    )) ?? {};
            } catch (e) {
                rollbackLists();
                restoreDirty();
                throw e;
            }
        }

        this._pruneUnchangedMany2ones(changes);

        const undoChanges = this._applyChanges(changes, onchangeServerValues, {
            undoable: true,
        });
        const changedSomething =
            Object.keys(changes).length > 0 ||
            Object.keys(onchangeServerValues).length > 0;
        if (!changedSomething) {
            restoreDirty();
            return;
        }
        try {
            await this._onUpdate({ withoutParentUpdate });
        } catch (e) {
            undoChanges();
            restoreDirty();
            throw e;
        }
        if (this.model.hasOnRecordChangedHook) {
            await this.model.notifyLifecycle(
                "onRecordChanged",
                this,
                this._getChanges(),
            );
        }
    }
}
