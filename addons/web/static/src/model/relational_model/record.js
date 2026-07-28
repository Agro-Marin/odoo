// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record - Field value management, change tracking, dirty state, and save/discard for individual records */

import { markRaw, toRaw } from "@odoo/owl";
import { omit } from "@web/core/utils/collections/objects";

import { DataPoint } from "./datapoint.js";
import { getBasicEvalContext, getFieldContext, isX2Many } from "./field_context.js";
import { Operation } from "./operation.js";
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
 *  currentValues?: RecordType<string, unknown>;
 *  orderBys?: RecordType<string, unknown>;
 *  withInvisible?: boolean;
 *  withReadonly?: boolean;
 *  keepChanges?: boolean;
 * }} FieldSpecifications
 *
 * @typedef {"edit" | "readonly"} Mode
 */

/** Shared no-op returned by ``_applyChanges`` when the caller opts out of undo. */
const NO_UNDO = () => {};

/**
 * Wrapper marking the multi-edit flow's answer on its way out of ``_update``.
 *
 * ``update`` has to tell "these changes went to the multi-edit flow" from
 * "nothing was dispatched", and it cannot read that off the value: ``_multiSave``
 * answers ``undefined`` whenever it declines — an empty changeset (a property
 * edit dropped by ``preprocessPropertiesChanges``) or a record already being
 * discarded. Reading that ``undefined`` as "not dispatched" made
 * ``update({save: true})`` fall through and individually save the very record
 * the multi-edit flow had just refused to touch.
 */
const MULTI_EDIT_RESULT = Symbol("multiEditResult");

export class RelationalRecord extends DataPoint {
    static type = "Record";

    /**
     * @type {typeof DataPoint.prototype.setup<{
     *  manuallyAdded?: boolean;
     *  onUpdate?: (params?: { withoutParentUpdate?: boolean }) => any;
     *  parentRecord?: RelationalRecord;
     *  virtualId?: string;
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
        this._saveInFlight = false;
        this._urgentBeaconFired = false;

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
        if (!keepChanges) {
            this._clearChanges();
        } else {
            this.dirty = this.dirty || !this._editState.isChangeSetEmpty;
            this._assertChangeSetInvariant();
        }
        this.data = { ...this._values, ...this._changes };
        this._initialTextValues = markRaw({ ...this._textValues });
        if (keepChanges) {
            Object.assign(this._textValues, this._getTextValues(this._changes));
        }
        this._setEvalContext();

        if (!keepChanges) {
            this._invalidFields.clear();
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

    archive(reload) {
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

    delete() {
        return this.model.mutex.exec(() => deleteRecord(this));
    }

    async discard() {
        if (this.model._closeUrgentSaveNotification) {
            this.model._closeUrgentSaveNotification();
        }
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

    toggleSelection(selected) {
        return this.model.mutex.exec(() => {
            this._toggleSelection(selected);
        });
    }

    unarchive(reload) {
        return this.model.mutex.exec(() => unarchive(this, reload));
    }

    /** @param {Object} changes @param {{ save?: boolean }} [options] */
    update(changes, { save } = {}) {
        if (this.model.urgentSave.isActive) {
            return this._update(changes);
        }
        return this.model.mutex.exec(async () => {
            const dispatched = await this._update(changes, { withoutOnchange: save });
            if (dispatched && MULTI_EDIT_RESULT in dispatched) {
                return dispatched[MULTI_EDIT_RESULT];
            }
            if (save && this.canSaveOnUpdate) {
                return this._save();
            }
        });
    }

    urgentSave() {
        if (toRaw(this)._saveInFlight) {
            return true;
        }
        return this.model.urgentSave.run(() => this._save({ reload: false }));
    }

    /** Reactive "record has unsaved edits" signal. @returns {boolean} */
    get dirty() {
        return this._editState.dirty;
    }

    set dirty(value) {
        this._editState.dirty = value;
    }

    /**
     * Read-accessor for the pending-edit bag. Returns the underlying
     * ``markRaw`` object by reference so existing consumers
     * (``Object.keys(record._changes)``, ``record._changes[fieldName] = value``
     * inside ``_applyChanges``, ``_getChanges(this._changes, ...)`` in the save
     * flow) keep working.
     *
     * @returns {Record<string, any>}
     */
    get _changes() {
        return this._editState.changes;
    }

    /**
     * Write-accessor for wholesale bag replacement (the undo path in
     * ``_applyChanges`` and the savepoint-restore path each capture and
     * later reinstall a snapshot). Preserves the ``markRaw`` invariant via
     * the owner's ``changes`` setter. Single-field writes
     * (``record._changes[fieldName] = value``) still go through the
     * underlying markRaw bag returned by the getter.
     */
    set _changes(initial) {
        this._editState.changes = initial;
    }

    /** @returns {Set<string>} fields that failed validation */
    get _invalidFields() {
        return this._editState.invalidFields;
    }

    set _invalidFields(value) {
        this._editState.invalidFields = value;
    }

    /** @returns {Set<string>} required fields currently left unset */
    get _unsetRequiredFields() {
        return this._editState.unsetRequiredFields;
    }

    /** @returns {() => void} closer for the open invalid-fields notification */
    get _closeInvalidFieldsNotification() {
        return this._editState.closeInvalidFieldsNotification;
    }

    set _closeInvalidFieldsNotification(value) {
        this._editState.closeInvalidFieldsNotification = value;
    }

    /** @returns {Record<string, any>} server false-vs-"" tracking (char/text/html) */
    get _textValues() {
        return this._editState.textValues;
    }

    set _textValues(value) {
        this._editState.textValues = value;
    }

    /** @returns {Record<string, any>} initial ``_textValues`` snapshot (no-savepoint discard) */
    get _initialTextValues() {
        return this._editState.initialTextValues;
    }

    set _initialTextValues(value) {
        this._editState.initialTextValues = value;
    }

    /** @returns {any} single-use savepoint snapshot (set by addSavePoint) */
    get _savePoint() {
        return this._editState.savePoint;
    }

    set _savePoint(value) {
        this._editState.savePoint = value;
    }

    /**
     * Atomically clear pending changes and reset the reactive ``dirty`` signal
     * (Invariant I3 — {@link RecordEditState#clearChanges}). Use whenever
     * ``_changes`` is being emptied; callers that also rebuild ``data`` or
     * replace ``_values`` keep that logic at the call site.
     */
    _clearChanges() {
        this._editState.clearChanges();
        this._assertChangeSetInvariant();
    }

    /**
     * Raise the reactive ``dirty`` signal without touching ``_changes``, for
     * paths that count the record modified before (or without) a field edit
     * reaching the bag — ``setInvalidField()`` (Invariant 2) and ``_update()``
     * (Invariant 1). Delegates to {@link RecordEditState#markDirty}.
     */
    _markDirty() {
        this._editState.markDirty();
    }

    /**
     * Debug-only invariant check on the (``_changes``, ``dirty``) pair (see
     * the field-level docstring in ``setup()``). The only legitimate states
     * are ``(false, empty)`` clean, ``(true, non-empty)`` modified, and
     * ``(true, empty)`` invalid input (Invariant 2) or the race window after
     * ``_markDirty`` before preprocessors land (Invariant 1). ``(false,
     * non-empty)`` must never persist past a checkpoint — the desync this
     * catches. Call sites: after ``_clearChanges`` and after both
     * ``_setData`` branches.
     *
     * Sanctioned producers of ``(false, non-empty)`` states BETWEEN
     * checkpoints — system-originated changes that deliberately don't count
     * as user edits:
     *   - the command engine's UPDATE case (static_list_command_engine.js)
     *     applies server-originated onchange commands via ``_applyChanges``
     *     without raising ``dirty``;
     *   - ``DynamicList._multiSave`` fans the edited record's changes out to
     *     the other selected records the same way;
     *   - ``StaticList._addNewRecordAtIndex`` force-resets ``dirty`` on the
     *     freshly inserted row while keeping ``_changes[handleField]`` so
     *     the sequence still ships with the parent's CREATE command.
     * A warning from this assert therefore points at a NEW desync only if a
     * ``_setData({keepChanges})``/``_clearChanges`` checkpoint ran while one
     * of those states was still live.
     *
     * Skipped in production; in debug mode emits ``console.warn`` (chosen
     * over ``throw`` — crashing on a desync is worse UX than the desync).
     */
    _assertChangeSetInvariant() {
        if (!odoo.debug) {
            return;
        }
        if (!this.dirty && !this._editState.isChangeSetEmpty) {
            console.warn(
                `[record] ChangeSet invariant violated on ${this.resModel}` +
                    `${this.resId ? `/${this.resId}` : "/new"}: ` +
                    `dirty=false but _changes is non-empty ` +
                    `(keys: ${Object.keys(this._changes).join(", ")}). ` +
                    `This pair must be cleared atomically — see ` +
                    `record.js _clearChanges() and the field-level ` +
                    `docstring in setup(). Likely cause: a new code path ` +
                    `mutated the _changes bag directly ` +
                    `without going through _update() (which calls _markDirty).`,
            );
        }
    }

    _addSavePoint() {
        addSavePoint(this);
    }

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
                // ``_checkValidity({removeInvalidOnly})`` prunes BOTH sets, and
                // the two must stay paired: ``_unsetRequiredFields`` is the
                // candidate list a later prune iterates, so restoring only
                // ``_invalidFields`` leaves a field flagged invalid that no
                // prune can ever revisit.
                for (const fieldName of unsetRequiredFields) {
                    this._unsetRequiredFields.add(fieldName);
                }
                // Keys ADDED during the change must go, not just be
                // overwritten: a rolled-back onchange carrying a properties
                // field left its per-property ``<field>.<name>`` entries
                // behind, so the record kept data for properties the undone
                // change invented.
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

    _applyValues(values) {
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

    /** @param {{ silent?: boolean, displayNotification?: boolean, removeInvalidOnly?: boolean, scopedFields?: Set<string> }} [options] */
    _checkValidity(options) {
        return checkValidity(this, options);
    }

    /**
     * Build the eval context for this record's current data, in both
     * virtual-id and real-id variants.
     *
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
        return new this.model.Class.StaticList(this.model, config, data, options);
    }

    _discard() {
        return discard(this);
    }

    _displayInvalidFieldNotification() {
        return displayInvalidFieldNotification(this);
    }

    _formatServerValue(fieldType, value) {
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
     * @param {FieldSpecifications} [params]
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

    _restoreActiveFields() {
        if (!this._activeFieldsToRestore) {
            return;
        }
        this.model._patchConfig(this.config, {
            activeFields: { ...this._activeFieldsToRestore },
        });
        this._activeFieldsToRestore = undefined;
    }

    /**
     * NOTE (finding 9): ``onError`` runs while ``model.mutex`` is HELD — the
     * public ``save()`` calls ``_save`` inside ``mutex.exec``, and in dialog
     * mode ``onError`` resolves only when the user closes the FormErrorDialog.
     * Its ``discard``/``retry`` actions therefore MUST use ``_``-prefixed
     * protected methods (``record._discard()``, the internal ``save(...)``);
     * calling a public mutex-taking verb from inside ``onError`` would deadlock.
     *
     * @param {{ reload?: boolean, onError?: (e: Error, actions: { discard: () => void, retry: () => any }) => any, nextId?: number }} [options]
     */
    async _save(options) {
        return save(this, options);
    }

    /**
     * For owl reactivity, it's better to only update the keys inside the evalContext
     * instead of replacing the evalContext itself, because a lot of components are
     * registered to the evalContext (but not necessarily keys inside it), and would
     * be uselessly re-rendered if we replace it by a brand new object.
     */
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
     * Pure, synchronous variant of {@link setInvalidField}: raises the
     * invalid flag without the multi-edit UI reaction (notification +
     * discard + mode switch) of ``record_validator.setInvalidField`` — the
     * async variant re-takes ``model.mutex`` through ``discard()``, so it
     * must not be called from mutex-held code. Does not touch ``dirty``:
     * callers restoring state (``_applyChanges``'s undo) own that flag.
     *
     * @param {string} fieldName
     */
    _setInvalidFieldFlag(fieldName) {
        this._invalidFields.add(fieldName);
    }

    _resetFieldValidity(fieldName) {
        return resetFieldValidity(this, fieldName);
    }

    /**
     * @param {Mode} mode
     */
    _switchMode(mode) {
        this.model._patchConfig(this.config, { mode });
        if (mode === "readonly") {
            this._noUpdateParent = false;
            this._invalidFields.clear();
        }
    }

    _toggleSelection(selected) {
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
            // Apply-then-undo looks like a no-op on STATE — and it is: the
            // changes have not been committed yet, so the undo restores what
            // was already there (``_update``'s ``rollbackLists`` owns the real
            // rollback, snapshotting before the preprocessors ran). What it is
            // NOT a no-op on is REACTIVITY: the field component is bound to
            // ``record.data``, and the user's rejected input lives only in the
            // DOM. Writing the new value and writing the old one back is what
            // notifies the subscriber, so the input re-renders from model truth
            // instead of keeping the value the server just refused.
            // Pinned by form_view.test.js "onchange returns an error".
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

    async _update(
        changes,
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
            if (raw._editState.isChangeSetEmpty && !raw._invalidFields.size) {
                this.dirty = wasDirty;
            }
        };
        const listSnapshots = [];
        for (const fieldName of Object.keys(changes)) {
            if (isX2Many(this.fields[fieldName])) {
                const list = toRaw(this.data)[fieldName];
                if (list?._commands) {
                    listSnapshots.push({ list, snapshot: list._snapshot() });
                }
            }
        }
        const rollbackLists = () => {
            for (const { list, snapshot } of listSnapshots) {
                list._restore(snapshot);
            }
        };
        const prom = Promise.all([
            preprocessMany2oneChanges(this, changes),
            preprocessMany2OneReferenceChanges(this, changes),
            preprocessReferenceChanges(this, changes),
            preprocessX2manyChanges(this, changes),
            preprocessPropertiesChanges(this, changes),
            preprocessHtmlChanges(this, changes),
        ]);
        try {
            await this.model.urgentSave.awaitUnlessUrgent(prom);
        } catch (e) {
            rollbackLists();
            restoreDirty();
            throw e;
        }
        if (this.selected && this.model.multiEdit) {
            const result = await this.model.multiEditDispatch(this, changes);
            // The multi-edit flow owns the cohort's state from here — it saves,
            // discards or declines. Drop the optimistic dirty mark taken above
            // if it left nothing pending on this record, so a declined dispatch
            // doesn't strand it as "modified" with an empty changeset.
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
        // Drop many2ones the preprocessor resolved to the value already held,
        // so re-picking the same record leaves the record clean.
        //
        // AFTER the onchange, not before, and that ordering is load-bearing:
        // editing a linked record through the m2o's external-open dialog writes
        // the SAME {id, display_name} back on save precisely to re-run the
        // parent's onchange against the linked record's new contents. Moving
        // this ahead of the RPC empties ``changes``, ``_getOnchangeValues``
        // finds no onChange field and skips the call, and the parent silently
        // keeps values computed from the pre-edit record. Pinned by
        // many2one_field.test.js "onchanges on many2ones trigger when editing
        // record in form view".
        for (const fieldName of Object.keys(changes)) {
            if (this.fields[fieldName].type === "many2one") {
                const curVal = toRaw(this.data[fieldName]);
                const nextVal = changes[fieldName];
                if (
                    curVal &&
                    nextVal &&
                    curVal.id === nextVal.id &&
                    curVal.display_name === nextVal.display_name
                ) {
                    delete changes[fieldName];
                }
            }
        }
        const undoChanges = this._applyChanges(changes, onchangeServerValues, {
            undoable: true,
        });
        if (
            Object.keys(changes).length > 0 ||
            Object.keys(onchangeServerValues).length > 0
        ) {
            try {
                await this._onUpdate({ withoutParentUpdate });
            } catch (e) {
                undoChanges();
                restoreDirty();
                throw e;
            }
            if (this.model.hasOnRecordChangedHook) {
                await this.model.hooks.lifecycle.onRecordChanged(
                    this,
                    this._getChanges(),
                );
            }
        } else {
            restoreDirty();
        }
    }
}
