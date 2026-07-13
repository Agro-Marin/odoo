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

        // Owner of the editable-state layer: the pending-edit change set, the
        // reactive ``dirty`` signal, the field-validity sets, char/text/html
        // false-vs-"" tracking, and the savepoint. Constructed first so the
        // delegating accessors below (``dirty``, ``_changes``, ``_invalidFields``,
        // ``_textValues``, ``_savePoint`` …) are usable for the rest of setup.
        // NOT ``markRaw``: reached through the record's reactive proxy it keeps
        // ``dirty``/``invalidFields`` reactive, while ``toRaw(record)._editState``
        // gives the raw owner for the raw reads in ``_update``. See
        // ``record_edit_state.js`` for the full reactivity + invariant contract.
        //
        // The (dirty, changes) invariants (documented at length in
        // ``STATE_MANAGEMENT.md``): (1) ``_update`` marks dirty before async
        // preprocessors populate ``_changes``; (2) ``setInvalidField`` marks
        // dirty even with an empty change set; (3) clearing the change set must
        // reset ``dirty`` atomically — always via ``_clearChanges()``
        // (``RecordEditState.clearChanges``). The ``keepChanges`` reload path in
        // ``_setData`` instead derives ``dirty`` from the preserved edit state.
        this._editState = new RecordEditState();

        this.selected = false;
        // True while a save's web_save RPC (and post-RPC state cleanup) is
        // on the wire — set/cleared by ``record_save.save``. ``urgentSave()``
        // reads it to skip the tab-close beacon when the same changes are
        // already being persisted.
        this._saveInFlight = false;

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
        // Field names whose values were genuinely provided (server rows or
        // caller values), as opposed to backfilled defaults below. Consumers
        // (``StaticList._getResIdsToLoad``) use it to decide whether a cached
        // record actually holds fetched values for a set of fields —
        // ``fieldNames``/``activeFields`` cannot tell: they describe what the
        // view wants, not what was loaded.
        /** @type {Set<string>} */
        this._loadedFieldNames = markRaw(new Set(Object.keys(data)));
        const missingFields = this.fieldNames.filter(
            (fieldName) => !(fieldName in data),
        );
        data = { ...this._getDefaultValues(missingFields), ...data };
        // ``_textValues`` (owned by ``this._editState``) tracks the raw server
        // value (false or string) of char/text/html fields: in the DB they can
        // be NULL or the empty string, indistinguishable in the UI but not in
        // the eval context. It lets us build the eval context correctly and
        // always expose string values (false → "") in ``this.data``.
        this._setData(data);
    }

    /**
     * @param {Record<string, any>} data
     * @param {FieldSpecifications} [params]
     */
    _setData(data, { orderBys, keepChanges } = {}) {
        this._isEvalContextReady = false;
        if (this.data) {
            // Not the constructor call (whose ``data`` includes backfilled
            // defaults — setup seeds ``_loadedFieldNames`` from the pre-merge
            // keys): every later call passes genuine server rows.
            for (const fieldName of Object.keys(data)) {
                this._loadedFieldNames.add(fieldName);
            }
        }
        if (this.resId) {
            // markRaw like the new-record branch below and every other _values
            // writer: without it, `data = {...this._values}` reads _values through
            // the reactive proxy and eagerly wraps every relational sub-value
            // (even undisplayed fields) on every existing-record load.
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
            // ``keepChanges`` preserves the whole pending-edit layer across
            // a server reload (stale-while-revalidate cache callbacks in
            // ``relational_model.js``) — only the server layer (``_values``)
            // is refreshed:
            //  - ``dirty`` must be derived from the preserved edit state,
            //    not reset: ``_changes`` non-empty OR pending invalid input
            //    (Invariant 2 — invalid input never reaches ``_changes``,
            //    but ``setInvalidField`` marked the record dirty, so
            //    ``dirty && _invalidFields.size`` is the evidence; testing
            //    ``_invalidFields`` alone would falsely flag a pristine
            //    record whose unset-required fields were flagged by
            //    ``_checkValidity``). A user edit racing the network
            //    revalidation would otherwise end up with ``dirty=false``,
            //    and every ``isDirty()`` gate (pager, action buttons)
            //    would silently discard it.
            //  - ``_invalidFields`` must survive (see below): the DOM input
            //    still holds the rejected text, so wiping the flags would
            //    let a save proceed without the value the user typed.
            //  - ``_savePoint`` must survive (see below): it snapshots that
            //    same pending-edit layer (see ``record_savepoint.js``),
            //    e.g. when an x2many form dialog opens; wiping it while
            //    keeping ``_changes`` would send a later Discard through
            //    the no-savepoint branch, clearing pre-dialog edits too.
            //  - a keepChanges reload must NEVER lower the flag: save and
            //    discard are the only legitimate lowering points. During the
            //    Invariant-1 window of an in-flight ``_update()`` (dirty=true,
            //    ``_changes`` still empty, no invalid fields — the record is
            //    between ``_markDirty()`` and ``_applyChanges()``), deriving
            //    dirty from ``_changeSet``/``_invalidFields`` alone would
            //    clear it and the pending edit would be silently discarded
            //    by the next ``isDirty()`` gate.
            this.dirty = this.dirty || !this._changeSet.isEmpty;
            this._assertChangeSetInvariant();
        }
        this.data = { ...this._values, ...this._changes };
        // ``_initialTextValues`` is the server-truth snapshot a no-savepoint
        // discard reverts to, so capture it from the freshly merged server text
        // values BEFORE overlaying any pending edit. markRaw for parity with
        // ``_textValues`` (both are non-reactive bags; the wholesale writers in
        // record_save.js also markRaw).
        this._initialTextValues = markRaw({ ...this._textValues });
        if (keepChanges) {
            // The server text values merged into ``_textValues`` above clobbered
            // the pending-edit layer's char/text/html values (this reload path
            // — stale-while-revalidate cache callbacks — refreshes only the
            // server layer). Re-overlay the pending edits so the eval context
            // matches what the user still sees in the inputs (mirrors
            // ``_applyValues``); ``_initialTextValues`` above stays server-truth.
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

    // -------------------------------------------------------------------------
    // Getter
    // -------------------------------------------------------------------------

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

    // -------------------------------------------------------------------------
    // Public
    // -------------------------------------------------------------------------

    archive() {
        return this.model.mutex.exec(() => archive(this));
    }

    /** @param {{ displayNotification?: boolean }} [options] */
    async checkValidity({ displayNotification } = {}) {
        await this.model.urgentSave.awaitUnlessUrgent(this.model._askChanges());
        if (this.model.urgentSave.isActive) {
            // Tab-close path must not queue behind ``model.mutex`` — it may be
            // held by the very save urgent mode is bypassing (mirrors
            // ``dynamic_list.leaveEditMode``).
            return this._checkValidity({ displayNotification });
        }
        // Serialize the mutating validity scan on the model mutex like every
        // other public verb: a queued ``_update`` applying an onchange must not
        // interleave with the scan and leave invalid flags on half-applied
        // data (which spuriously aborts a concurrent pager load).
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
        // Invariant 2: invalid input never reaches ``_changes`` (the user's
        // value failed type validation), but the record is still considered
        // modified — the form should show "Unsaved changes" and block
        // navigation. Standalone dirty mark, no ``_changes`` reset.
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

    unarchive() {
        return this.model.mutex.exec(() => unarchive(this));
    }

    /** @param {Object} changes @param {{ save?: boolean }} [options] */
    update(changes, { save } = {}) {
        if (this.model.urgentSave.isActive) {
            return this._update(changes);
        }
        return this.model.mutex.exec(async () => {
            const dispatched = await this._update(changes, { withoutOnchange: save });
            if (dispatched !== undefined) {
                // multiEditDispatch already handled the save for the whole
                // selection; its result (false on validation failure or a
                // declined confirmation) must reach callers like
                // dynamic_group_list.moveRecord, whose revert logic keys on
                // it. Running _save() on top would hit the no-changes early
                // return and mask the failure as `true`.
                return dispatched;
            }
            if (save && this.canSaveOnUpdate) {
                return this._save();
            }
        });
    }

    urgentSave() {
        // Raw read: ``this`` can be a component-bound reactive proxy
        // (controllers call ``editedRecord.urgentSave()``); reading the
        // flag through it would subscribe that component to a marker that
        // ``record_save.save`` toggles around every RPC.
        if (toRaw(this)._saveInFlight) {
            // A normal save for this record is already on the wire: firing
            // the beacon would re-serialize the same ``_changes`` — x2many
            // CREATE commands included, which are not idempotent — and
            // duplicate child rows. The in-flight save either lands or the
            // server-side concurrency check rejects it; nothing is lost by
            // skipping.
            return true;
        }
        return this.model.urgentSave.run(() => this._save({ reload: false }));
    }

    // -------------------------------------------------------------------------
    // Protected
    // -------------------------------------------------------------------------

    // -------------------------------------------------------------------------
    // Editable-state accessors — the state lives in ``this._editState``
    // ({@link RecordEditState}); these record-level getters/setters keep every
    // existing consumer working unchanged (``record.dirty``,
    // ``record._invalidFields.add(…)``, ``record._changes[f] = v``, the sibling
    // helpers, the test mocks). Reactivity is preserved because ``_editState``
    // is not ``markRaw``: through the reactive record proxy these read/write
    // reactive owner fields, while ``toRaw(record)._editState`` gives the raw
    // owner for the raw reads in ``_update``.
    // -------------------------------------------------------------------------

    /** Reactive "record has unsaved edits" signal. @returns {boolean} */
    get dirty() {
        return this._editState.dirty;
    }

    set dirty(value) {
        this._editState.dirty = value;
    }

    /** The pending-edit change set. @returns {import("./change_set").ChangeSet} */
    get _changeSet() {
        return this._editState.changeSet;
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
     * {@link ChangeSet#replace}. Single-field writes
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
        if (!this.dirty && !this._changeSet.isEmpty) {
            console.warn(
                `[record] ChangeSet invariant violated on ${this.resModel}` +
                    `${this.resId ? `/${this.resId}` : "/new"}: ` +
                    `dirty=false but _changes is non-empty ` +
                    `(keys: ${Object.keys(this._changes).join(", ")}). ` +
                    `This pair must be cleared atomically — see ` +
                    `record.js _clearChanges() and the field-level ` +
                    `docstring in setup(). Likely cause: a new code path ` +
                    `mutated _changes through the ChangeSet.raw getter ` +
                    `without going through _update() (which calls _markDirty).`,
            );
        }
    }

    _addSavePoint() {
        addSavePoint(this);
    }

    _applyChanges(changes, serverChanges = {}) {
        // We need to generate the undo function before applying the changes
        const initialTextValues = { ...this._textValues };
        const initialChanges = { ...this._changes };
        const initialData = { ...toRaw(this.data) };
        const initialDirty = this.dirty;
        const invalidFields = [...toRaw(this._invalidFields)];
        const undoChanges = () => {
            for (const fieldName of invalidFields) {
                // Flag-only restore: the async setInvalidField re-takes the
                // mutex through discard() in multi-edit, and these flags
                // already passed the lifecycle hook when first raised.
                this._setInvalidFieldFlag(fieldName);
            }
            Object.assign(this.data, initialData);
            this._changes = markRaw(initialChanges);
            Object.assign(this._textValues, initialTextValues);
            this.dirty = initialDirty;
            this._setEvalContext();
        };

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

        // mark changed fields as valid if they were not, and re-evaluate required attributes
        // for the fields whose unset-required status could actually change with those changes
        // (the changed fields plus those whose invisible/required/readonly modifier references
        // one of them). ``removeInvalidOnly`` only *prunes* newly-valid fields, so scoping the
        // scan cannot miss a field: a field outside the scope cannot have flipped status.
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
        // X2many pending-edit lists must not be wholesale-replaced by a
        // freshly parsed StaticList: the replacement has empty ``_commands``,
        // silently dropping the user's pending sub-edits from the next save
        // (extendRecord's first-extension load, m2m-grouped sibling updates).
        // Merge the fresh server rows into the existing list instead, and
        // parse only the other fields.
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
     * Given a possibily incomplete value for a many2one field (i.e. a object { id, display_name } but
     * with id and/or display_name being undefined), return the complete value as follows:
     *  - if a display_name is given but no id, perform a name_create to get an id
     *  - if an id is given but display_name is undefined, call web_read to get the display_name
     *  - if both id and display_name are given, return the value as is
     *  - in any other cases, return false
     *
     * @param {{ id?: number; display_name?: string }} value
     * @param {string} fieldName
     * @param {string} resModel
     * @returns {Promise<false | { id: number; display_name: string; }>} the completed record { id, display_name } or false
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
            context: {}, // will be set afterwards, see "_updateContext" in "_setEvalContext"
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
        // Delegate to the pure ``computeChangeset`` (record_utils.js): the two
        // used to carry identical hand-inlined copies of this algorithm — the
        // duplication rotted (``computeChangeset`` had no live caller and was
        // only exercised by its own unit tests). ``_isReadonly`` /
        // ``_formatServerValue`` / ``isNew`` are thin delegators to the same
        // primitives ``computeChangeset`` uses, so behaviour is unchanged; the
        // existing changeset unit-tests now cover the live path.
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

    /** @param {{ reload?: boolean, onError?: (e: Error, actions: { discard: () => void, retry: () => any }) => any, nextId?: number }} [options] */
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
            // Deselecting invalidates a "whole domain selected" state; the
            // bookkeeping is owned by the root list (no-op when the root
            // isn't a list, e.g. form views).
            this.model.root._onRecordDeselected?.();
        }
    }

    /**
     * @param {Record<string, any>} changes
     * @returns {Promise<Record<string, any>>}
     */
    async _getOnchangeValues(changes) {
        // Compute Operations (multi-edit "+5"/"-5" inputs) into a LOCAL copy:
        // rewriting the caller's `changes` in place would replay an absolute
        // number if the caller re-dispatches the same object (same
        // non-mutation contract as `effectiveChanges` in `_update`).
        // `_applyChanges` computes Operations itself, off the same base.
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
                // We apply changes and revert them after to force a render of the Field components
                const undoChanges = this._applyChanges(changes);
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
        // Invariant 1: race-protection. ``_changes`` is populated by
        // ``_applyChanges`` further below, after async preprocessors and
        // (optional) onchange RPC complete. Setting ``dirty`` synchronously
        // here means UI bindings reflect "modified" the moment a field
        // update is dispatched, not after a network round-trip.
        //
        // Snapshot through the RAW datapoint: ``this`` may be a
        // component-bound reactive proxy (field components dispatch
        // ``record.update(...)`` on their own ``props.record``), and reading
        // ``dirty`` through it would SUBSCRIBE that component to the very
        // flag ``_markDirty()`` writes on the next line — re-rendering the
        // dispatching field mid-update, whose ``useInputField`` effect then
        // resyncs the input to the stale pre-onchange model value (lost
        // keystrokes under a slow onchange, wrong urgent-save payloads on
        // tab close).
        const raw = toRaw(this);
        const wasDirty = raw.dirty;
        this._markDirty();
        // Invariant 1's provisional mark must not outlive an update that
        // turns out to be a no-op or fails — otherwise ``isDirty()`` gates
        // (pager, breadcrumbs, beforeLeave) chase changes that don't exist.
        // Only lower the flag when nothing else keeps the record modified
        // (pending changes or invalid input). Same raw-read rule as above:
        // ``_invalidFields`` is a reactive Set, and probing its ``size``
        // through the caller's proxy would subscribe the dispatching
        // component to every validity change of the record.
        const restoreDirty = () => {
            if (raw._changeSet.isEmpty && !raw._invalidFields.size) {
                this.dirty = wasDirty;
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
        // The preprocessors are kicked off above so their fire-and-forget
        // bookkeeping happens; on the tab-close path we skip awaiting them
        // because the browser may kill us before they settle.
        // A preprocessor CAN reject (m2o quick-create AccessError, webRead
        // failure completing a reference): the change never stuck, so lower
        // the provisional dirty mark before rethrowing — otherwise the record
        // shows "unsaved changes" forever and pager/breadcrumb gates chase an
        // edit that isn't in the model. (The no-op / _onUpdate-failure paths
        // below already restore for the same reason.)
        try {
            await this.model.urgentSave.awaitUnlessUrgent(prom);
        } catch (e) {
            restoreDirty();
            throw e;
        }
        if (this.selected && this.model.multiEdit) {
            // Model-level dispatch installed by the root DynamicList — a
            // record must not reach into the list's protected ``_multiSave``.
            return this.model.multiEditDispatch(this, changes);
        }
        let onchangeServerValues = {};
        if (!withoutOnchange) {
            // ``unlessUrgent`` (not ``awaitUnlessUrgent``): the onchange
            // RPC must NOT fire on tab close — sending it would race the
            // sendBeacon save, queueing a server-side computation against
            // a session that is about to disappear.
            // A failed onchange (e.g. a ValidationError raised by the server)
            // is deliberately NOT caught to restore the dirty flag: the user's
            // edit is real and still pending, so the record must stay dirty —
            // the Save button remains available for a retry and the edit isn't
            // silently discarded. (Lowering the provisional dirty mark here
            // would hide the Save button after the very edit that triggered the
            // error.) The no-op / _onUpdate-failure paths below still restore,
            // since there the change never stuck.
            onchangeServerValues =
                (await this.model.urgentSave.unlessUrgent(() =>
                    this._getOnchangeValues(changes),
                )) ?? {};
        }
        // A many2one re-set to its CURRENT value must still trigger the onchange
        // (that already ran above), but must NOT be recorded as a parent change.
        // Filter such no-op m2o entries into a local object instead of mutating
        // the caller's `changes` argument — `_update` had been rewriting its own
        // input in place, a side-effect surprise for any caller that reuses the
        // object. Cloned lazily so the common path (nothing to filter) allocates
        // nothing. The result feeds both `_applyChanges` and the "did anything
        // change?" gate below, exactly as the in-place delete used to.
        let effectiveChanges = changes;
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
                    if (effectiveChanges === changes) {
                        effectiveChanges = { ...changes };
                    }
                    delete effectiveChanges[fieldName];
                }
            }
        }
        const undoChanges = this._applyChanges(effectiveChanges, onchangeServerValues);
        if (
            Object.keys(effectiveChanges).length > 0 ||
            Object.keys(onchangeServerValues).length > 0
        ) {
            try {
                await this._onUpdate({ withoutParentUpdate });
            } catch (e) {
                undoChanges();
                restoreDirty();
                throw e;
            }
            // Only serialize the changeset when a real consumer is listening;
            // the default hook is a no-op and ``_getChanges()`` (recursive x2many
            // command build for new records / dirty x2many) would be discarded.
            if (this.model.hasOnRecordChangedHook) {
                await this.model.hooks.lifecycle.onRecordChanged(
                    this,
                    this._getChanges(),
                );
            }
        } else {
            // The m2o no-op filter emptied the update (a many2one re-set to
            // its current value): nothing was applied, so nothing is dirty.
            restoreDirty();
        }
    }
}
