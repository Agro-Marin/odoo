// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record - Field value management, change tracking, dirty state, and save/discard for individual records */

import { markRaw, toRaw } from "@odoo/owl";

import { ChangeSet } from "./change_set.js";
import { DataPoint } from "./datapoint.js";
import { getBasicEvalContext, getFieldContext } from "./field_context.js";
import { Operation } from "./operation.js";
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

        // Pending-edit accumulator. ``markRaw`` keeps the ChangeSet itself
        // out of OWL's reactivity graph (its internal ``_changes`` bag is
        // already ``markRaw`` for the same reason — see ``change_set.js``
        // for the full rationale). The Record exposes the underlying bag
        // via the ``_changes`` getter/setter below so existing consumers
        // that iterate ``Object.keys(record._changes)`` keep working.
        this._changeSet = markRaw(new ChangeSet());

        // Reactive signal indicating whether the record has unsaved edits.
        //
        // Invariants enforced by paired helpers:
        //   1. ``dirty`` is true after ``_update()`` is called, even before
        //      async preprocessors have populated ``_changes`` (race
        //      protection — set via ``_markDirty()`` at the top of
        //      ``_update`` so UI bindings reflect "modified" the moment a
        //      field update is dispatched, not after a network round-trip).
        //   2. ``setInvalidField()`` sets dirty=true even when ``_changes``
        //      is empty (invalid user input is not in the change log but
        //      the record is still considered modified — also routed
        //      through ``_markDirty()``).
        //   3. Whenever ``_changes`` is cleared, ``dirty`` MUST be reset
        //      on the same atomic step — use ``_clearChanges()``. The
        //      ``keepChanges`` reload path instead derives ``dirty`` from
        //      the preserved change set and invalid-field flags (see
        //      ``_setData`` — Invariant 2 must survive that reload).
        //
        // Field components debounce typing locally; ``isDirty()`` (async)
        // first calls ``model._askChanges()`` to flush pending field-level
        // edits before reading this signal. Sync reads are safe in code
        // paths that have already drained pending changes (post-mutex
        // critical sections, post-flush callbacks).
        this.dirty = false;
        this.selected = false;

        /** @type {Set<string>} */
        this._invalidFields = new Set();
        /** @type {Set<string>} */
        this._unsetRequiredFields = markRaw(new Set());
        this._closeInvalidFieldsNotification = () => {};

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
        const missingFields = this.fieldNames.filter(
            (fieldName) => !(fieldName in data),
        );
        data = { ...this._getDefaultValues(missingFields), ...data };
        // In db, char, text and html fields can be not set (NULL) and set to the empty string. In
        // the UI, there's no difference, but in the eval context, it's not the same. The next
        // structure keeps track of the server values we received for those fields (which can thus
        // be false or a string). This allows us to properly build the eval context, and to always
        // expose string values (false fallbacks on the empty string) in this.data.
        this._textValues = markRaw({});
        this._setData(data);
    }

    /**
     * @param {Record<string, any>} data
     * @param {FieldSpecifications} [params]
     */
    _setData(data, { orderBys, keepChanges } = {}) {
        this._isEvalContextReady = false;
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
        this._setEvalContext();
        this._initialTextValues = { ...this._textValues };

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
        return this._checkValidity({ displayNotification });
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
        return this.model.urgentSave.run(() => this._save({ reload: false }));
    }

    // -------------------------------------------------------------------------
    // Protected
    // -------------------------------------------------------------------------

    /**
     * Read-accessor for the pending-edit bag, delegating to the internal
     * {@link ChangeSet}. Returns the underlying ``markRaw`` object by
     * reference so existing consumers (``Object.keys(record._changes)``,
     * ``record._changes[fieldName] = value`` inside ``_applyChanges``,
     * ``_getChanges(this._changes, ...)`` in the save flow) keep working.
     *
     * @returns {Record<string, any>}
     */
    get _changes() {
        return this._changeSet.raw;
    }

    /**
     * Write-accessor for wholesale bag replacement (the undo path in
     * ``_applyChanges`` and the savepoint-restore path each capture and
     * later reinstall a snapshot). Delegates to {@link ChangeSet#replace}
     * to preserve the ``markRaw`` invariant. Single-field writes
     * (``record._changes[fieldName] = value``) still go through the
     * setter on the underlying bag, which is the markRaw object.
     */
    set _changes(initial) {
        this._changeSet.replace(initial);
    }

    /**
     * Atomically clear pending changes and reset the reactive ``dirty``
     * signal. The two assignments MUST happen as a pair: ``_changes`` is
     * ``markRaw`` (intentionally non-reactive, see ``ChangeSet``), so a
     * caller that only clears ``_changes`` would leave bindings on
     * ``record.dirty`` showing "modified" until the next mutation hits.
     *
     * Use this whenever ``_changes`` is being emptied. Callers that need
     * to also rebuild ``data`` or replace ``_values`` keep that logic at
     * the call site — the helper covers only the invariant that pairs
     * the two fields.
     */
    _clearChanges() {
        this._changeSet.clear();
        this.dirty = false;
        this._assertChangeSetInvariant();
    }

    /**
     * Set the reactive ``dirty`` signal without touching ``_changes``.
     * Used by paths that consider the record modified before the change
     * bag is populated — ``setInvalidField()`` (invariant 2; invalid
     * input never reaches ``_changes``) and ``_update()`` (invariant 1;
     * race protection — UI binds to "modified" the moment a field update
     * is dispatched, before async preprocessors land).
     */
    _markDirty() {
        this.dirty = true;
    }

    /**
     * Debug-only invariant check on the (``_changes``, ``dirty``) pair.
     *
     * The contract (see the field-level docstring in ``setup()`` lines
     * ~95-110): three legitimate states exist —
     *
     *   - ``(dirty=false, _changes empty)``    — clean record
     *   - ``(dirty=true,  _changes non-empty)``— modified record
     *   - ``(dirty=true,  _changes empty)``    — invalid input (Invariant 2)
     *     OR race window after _markDirty before preprocessors land (Invariant 1)
     *
     * The state that MUST NEVER persist past an atomic checkpoint is
     * ``(dirty=false, _changes non-empty)`` — the desync this assertion
     * exists to catch.  Call sites are checkpoints where the invariant
     * must strictly hold: after ``_clearChanges`` and after both
     * ``_setData`` branches (the ``keepChanges: true`` path derives
     * ``dirty`` from the preserved change set and invalid-field flags,
     * so it upholds the invariant too).
     *
     * Production: silent (assertion skipped entirely).  Debug: emits
     * ``console.warn`` with a structured payload so the offending
     * mutation can be traced.  Chosen over ``throw`` because crashing
     * the page on a desync is worse UX than the desync itself; the
     * warning surfaces the bug to the developer without losing user data.
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
        const invalidFields = [...toRaw(this._invalidFields)];
        const undoChanges = () => {
            for (const fieldName of invalidFields) {
                this.setInvalidField(fieldName);
            }
            Object.assign(this.data, initialData);
            this._changes = markRaw(initialChanges);
            Object.assign(this._textValues, initialTextValues);
            this._setEvalContext();
        };

        // Apply changes
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

        // Apply server changes
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
        const newValues = this._parseServerValues(values);
        Object.assign(this._values, newValues);
        for (const fieldName of Object.keys(newValues)) {
            if (fieldName in this._changes) {
                if (["one2many", "many2many"].includes(this.fields[fieldName].type)) {
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
                if (["one2many", "many2many"].includes(this.fields[fieldName].type)) {
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
        this._markDirty();
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
        await this.model.urgentSave.awaitUnlessUrgent(prom);
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
        }
    }
}
