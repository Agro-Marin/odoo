// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/static_list - In-memory x2many list: add, remove, reorder records and generate ORM commands */

import { markRaw } from "@odoo/owl";
import { deepEqual, omit } from "@web/core/utils/collections/objects";

import { serializeCommands } from "./command_builder.js";
import { x2ManyCommands } from "./commands.js";
import { DataPoint } from "./datapoint.js";
import { getBasicEvalContext, getId, isX2Many } from "./field_context.js";
import { completeActiveFields, patchActiveFields } from "./field_metadata.js";
import { fromUnityToServerValues } from "./field_values.js";
import { invalidateModifierDependencies } from "./record_utils.js";
import { applyCommands } from "./static_list_command_engine.js";
import { resequence, sort as sortRecords, sortBy } from "./static_list_sort.js";
import { copyRecordData } from "./static_list_utils.js";

/** @import { RelationalRecord } from "./record.js" */

export class StaticList extends DataPoint {
    static type = "StaticList";

    /**
     * @param {any} _config
     * @param {any} data
     * @param {any} [options]
     */
    setup(_config, data, options = {}) {
        this._parent = options.parent;
        this._onUpdate = options.onUpdate;

        this._cache = markRaw({});
        this._commands = [];
        this._initialCommands = [];
        /**
         * Pending ``_applyCommands`` result (see ``_trackCommandsPromise``);
         * null when none is in flight.
         * @type {Promise<void> | null}
         */
        this._commandsPromise = null;
        this._savePoint = undefined;
        this._unknownRecordCommands = {}; // tracks update commands on records we haven't fetched yet
        this._currentIds = [...this.resIds];
        this._needsReordering = false;
        this._tmpIncreaseLimit = 0;
        // Records already opened in a form dialog (kanban / non-editable list),
        // whose activeFields we've already extended with the dialog's fields.
        this._extendedRecords = new Set();

        /** @type {RelationalRecord[]} */
        this.records = data
            .slice(this.offset, this.offset + this.limit)
            .map((r) => this._createRecordDatapoint(r));
        this.count = this.resIds.length;
        this.handleField = Object.keys(this.activeFields).find(
            (fieldName) => this.activeFields[fieldName].isHandle,
        );
    }

    // -------------------------------------------------------------------------
    // Getters
    // -------------------------------------------------------------------------

    get currentIds() {
        return this._currentIds;
    }

    get editedRecord() {
        return this.records.find((record) => record.isInEdition);
    }

    get evalContext() {
        /** @type {any} */
        const evalContext = getBasicEvalContext(this.config);
        evalContext.parent = this._parent.evalContext;
        return evalContext;
    }

    get limit() {
        return this.config.limit ?? 0;
    }

    get offset() {
        return this.config.offset ?? 0;
    }

    get orderBy() {
        return this.config.orderBy;
    }

    get resIds() {
        return this.config.resIds ?? [];
    }

    get selection() {
        return [];
    }

    // -------------------------------------------------------------------------
    // Public
    // -------------------------------------------------------------------------

    /**
     * Adds a new record to an x2many relation: params.record if given (e.g.
     * after saving a form dialog), otherwise a Record built via onchange
     * (e.g. after "Add a line" in an editable list).
     *
     * @param {Object} params
     * @param {"top"|"bottom"} [params.position]
     * @param {Object} [params.activeFields=this.activeFields]
     * @param {boolean} [params.withoutParent=false]
     * @param {Object} [params.context]
     * @param {string} [params.mode]
     */
    addNewRecord(params) {
        return this.model.mutex.exec(async () => {
            const { activeFields, context, mode, position, withoutParent } = params;
            const record = await this._createNewRecordDatapoint({
                activeFields,
                context,
                position,
                withoutParent,
                manuallyAdded: true,
                mode,
            });
            await this._addRecord(record, { position });
            await this._onUpdate({
                withoutOnchange: !record._checkValidity({ silent: true }),
            });
            return record;
        });
    }

    /**
     * @param {number} index
     * @param {Object} [options]
     * @param {Object} [options.context]
     * @param {"edit" | "readonly"} [options.mode]
     */
    addNewRecordAtIndex(index, options = {}) {
        return this.model.mutex.exec(async () => {
            const newRecord = await this._addNewRecordAtIndex(index, options);
            await this._onUpdate();
            return newRecord;
        });
    }

    /**
     * @param {[number, any, any][]} commands
     * @param {Object} [options]
     * @param {boolean} [options.canAddOverLimit]
     * @param {boolean} [options.sort]
     * @returns {Promise<void>}
     */
    applyCommands(commands, options = {}) {
        return this.model.mutex.exec(async () => {
            await this._applyCommands(commands, omit(options, "sort"));
            if (options.sort) {
                await sortRecords(this);
            }
            await this._onUpdate();
        });
    }

    canResequence() {
        return (
            this.handleField &&
            this.orderBy.length &&
            this.orderBy[0].name === this.handleField
        );
    }

    delete(record) {
        return this.model.mutex.exec(async () => {
            await this._applyCommands([
                x2ManyCommands.delete(record.resId || record._virtualId),
            ]);
            // All records of last page are deleted => reload the new last page
            if (this.count === this.offset) {
                await this._load({
                    offset: Math.max(this.offset - this.limit, 0),
                });
            }
            await this._onUpdate();
        });
    }

    /**
     * @param {RelationalRecord[]} records
     * @param {Object} [options={}]
     * @param {number} [options.targetIndex]
     * @returns {Promise<void>}
     */
    duplicateRecords(records = [], options = {}) {
        return this.model.mutex.exec(async () => {
            await this._duplicateRecords(records, options);
            await this._onUpdate();
        });
    }

    async enterEditMode(record) {
        const canProceed = await this.leaveEditMode();
        if (canProceed) {
            await record.switchMode("edit");
        }
        return canProceed;
    }

    /**
     * Used when an x2many record is viewed/edited through a form view dialog
     * (e.g. x2many kanban or non-editable list), whose form typically has
     * different fields than the kanban/list: "extend" fields and activeFields,
     * patching an existing record's config or creating a new one with them.
     *
     * @param {Object} params
     * @param {Object} params.activeFields
     * @param {Object} params.fields
     * @param {Object} [params.context]
     * @param {boolean} [params.withoutParent]
     * @param {string} [params.mode]
     * @param {RelationalRecord} [record]
     * @returns {Promise<RelationalRecord>}
     */
    extendRecord(params, record) {
        return this.model.mutex.exec(async () => {
            // extend fields and activeFields of the list with those given in params
            completeActiveFields(this.config.activeFields, params.activeFields);
            // ``completeActiveFields`` mutates ``this.config.activeFields`` in
            // place (adding the dialog's fields), so drop any stale memoised
            // modifier-dependency map keyed on it.
            invalidateModifierDependencies(this.config.activeFields);
            Object.assign(this.fields, params.fields);
            const activeFields = { ...params.activeFields };
            for (const fieldName of Object.keys(this.activeFields)) {
                if (fieldName in activeFields) {
                    patchActiveFields(
                        activeFields[fieldName],
                        this.activeFields[fieldName],
                    );
                } else {
                    activeFields[fieldName] = this.activeFields[fieldName];
                }
            }

            if (record) {
                record._noUpdateParent = true;
                record._activeFieldsToRestore = { ...this.config.activeFields };
                /** @type {any} */
                const config = {
                    ...record.config,
                    ...params,
                    activeFields,
                    // Keep the list's live, merged ``fields`` object (identity ===
                    // ``list.fields``), not the caller's ``params.fields`` snapshot,
                    // which diverges from it over time as properties splice /
                    // applyCommands mutate the two independently.
                    fields: this.fields,
                };

                // case 1: the record already exists
                if (this._extendedRecords.has(record.id)) {
                    // case 1.1: the record has already been extended
                    // -> simply store a savepoint
                    this.model._patchConfig(record.config, config);
                    record._addSavePoint();
                    return record;
                }
                // case 1.2: extended for the first time, possibly with more fields.
                // Load values for existing records, apply defaults, update config
                // recursively, then save — in that order, so the model mutates once
                // per tick and datapoints have the right config when receiving values.
                let data = {};
                if (!record.isNew) {
                    const evalContext = Object.assign(
                        {},
                        record.evalContext,
                        config.context,
                    );
                    const resIds = /** @type {number[]} */ ([record.resId]);
                    [data] = await this.model._loadRecords(
                        { ...config, resIds },
                        evalContext,
                    );
                }
                this.model._patchConfig(record.config, config);
                record._applyDefaultValues();
                for (const fieldName of Object.keys(record.activeFields)) {
                    if (isX2Many(record.fields[fieldName])) {
                        const list = record.data[fieldName];
                        const patch = {
                            activeFields: activeFields[fieldName].related.activeFields,
                            fields: activeFields[fieldName].related.fields,
                        };
                        for (const subRecord of Object.values(list._cache)) {
                            this.model._patchConfig(subRecord.config, patch);
                        }
                        this.model._patchConfig(list.config, patch);
                    }
                }
                record._applyValues(data);
                const commands = this._unknownRecordCommands[record.resId];
                delete this._unknownRecordCommands[record.resId];
                if (commands) {
                    // await before _addSavePoint, so the savepoint doesn't
                    // snapshot a state where commands are partially applied
                    await this._applyCommands(commands);
                }
                record._addSavePoint();
            } else {
                // case 2: new record — create it with the extended config
                record = await this._createNewRecordDatapoint({
                    activeFields,
                    context: params.context,
                    withoutParent: params.withoutParent,
                    manuallyAdded: true,
                });
                record._activeFieldsToRestore = { ...this.config.activeFields };
                record._noUpdateParent = true;
            }
            // mark the record as being extended, to go through case 1.1 next time
            this._extendedRecords.add(record.id);

            return record;
        });
    }

    forget(record) {
        return this.model.mutex.exec(async () => {
            await this._applyCommands([x2ManyCommands.unlink(record.resId)]);
            await this._onUpdate();
        });
    }

    /** @param {{ discard?: boolean, canAbandon?: boolean, validate?: boolean }} [options] */
    async leaveEditMode({ discard, canAbandon, validate } = {}) {
        if (this.editedRecord) {
            await this.model._askChanges();
        }
        return this.model.mutex.exec(async () => {
            let editedRecord = this.editedRecord;
            if (editedRecord) {
                const isValid = editedRecord._checkValidity();
                if (!isValid && validate) {
                    return false;
                }
                if (canAbandon !== false && !validate) {
                    this._abandonRecords([editedRecord], { force: true });
                }
                // if we still have an editedRecord, it means it hasn't been abandonned
                editedRecord = this.editedRecord;
                if (editedRecord) {
                    if (isValid && !editedRecord.dirty && discard) {
                        return false;
                    }
                    if (
                        isValid ||
                        (!editedRecord.dirty && !editedRecord._manuallyAdded)
                    ) {
                        editedRecord._switchMode("readonly");
                    }
                }
            }
            return !this.editedRecord;
        });
    }

    linkTo(resId, serverData) {
        return this.model.mutex.exec(async () => {
            await this._applyCommands([[x2ManyCommands.LINK, resId, serverData]]);
            await this._onUpdate();
        });
    }

    unlinkFrom(resId, serverData) {
        return this.model.mutex.exec(async () => {
            await this._applyCommands([[x2ManyCommands.UNLINK, resId, serverData]]);
            await this._onUpdate();
        });
    }

    /** @param {{ limit?: number, offset?: number, orderBy?: object[] }} [options] */
    async load({ limit, offset, orderBy } = {}) {
        // Flush pending edits BEFORE taking the mutex (mirror ``leaveEditMode``'s
        // prelude): the public ``editedRecord.checkValidity()`` awaits
        // ``model._askChanges()`` (``mutex.getUnlockedDef``) and then re-takes
        // ``model.mutex`` itself — calling it from inside our own
        // ``mutex.exec`` would deadlock the non-reentrant mutex. Use the
        // protected ``_checkValidity`` (no mutex re-entry) inside the callback.
        if (this.editedRecord) {
            await this.model._askChanges();
        }
        return this.model.mutex.exec(async () => {
            const editedRecord = this.editedRecord;
            if (editedRecord && !editedRecord._checkValidity()) {
                return;
            }
            limit = limit !== undefined ? limit : this.limit;
            offset = offset !== undefined ? offset : this.offset;
            orderBy = orderBy !== undefined ? orderBy : this.orderBy;
            return this._load({ limit, offset, orderBy });
        });
    }

    moveRecord(dataRecordId, _dataGroupId, refId, _targetGroupId) {
        return this.resequence(dataRecordId, refId);
    }

    sortBy(fieldName) {
        return this.model.mutex.exec(() => sortBy(this, fieldName));
    }

    /** @param {{ add?: number[], remove?: number[] }} [options] */
    async addAndRemove({ add, remove } = {}) {
        return this.model.mutex.exec(async () => {
            const commands = [
                ...(add || []).map((id) => x2ManyCommands.link(id)),
                ...(remove || []).map((id) => x2ManyCommands.unlink(id)),
            ];
            await this._applyCommands(commands, { canAddOverLimit: true });
            await this._onUpdate();
        });
    }

    async resequence(movedId, targetId) {
        return this.model.mutex.exec(() => resequence(this, movedId, targetId));
    }

    /**
     * Called when a record previously extended for a form view dialog (see
     * extendRecord) is saved: adds it to the list if new, notifies the parent,
     * and re-sorts if needed.
     *
     * @param {RelationalRecord} record
     */
    validateExtendedRecord(record) {
        return this.model.mutex.exec(async () => {
            if (
                !this._currentIds.includes(
                    record.isNew ? record._virtualId : record.resId,
                )
            ) {
                // new record created, not yet in the list
                await this._addRecord(record);
            } else if (!record.dirty) {
                return;
            }
            await this._onUpdate();
            record._restoreActiveFields();
            record._savePoint = undefined;
        });
    }

    // -------------------------------------------------------------------------
    // Protected
    // -------------------------------------------------------------------------

    _abandonRecords(
        records = this.records,
        /** @type {{ force?: boolean }} */ { force } = {},
    ) {
        for (const record of records) {
            if (record.canBeAbandoned && (force || !record._checkValidity())) {
                const virtualId = record._virtualId;
                const idIndex = this._currentIds.findIndex((id) => id === virtualId);
                if (idIndex < 0) {
                    // Not in the list (e.g. a dialog-created record not yet
                    // validated): splice(-1, 1) would corrupt the list by
                    // removing its LAST id instead.
                    continue;
                }
                this._currentIds.splice(idIndex, 1);
                const recordIndex = this.records.findIndex((r) => r === record);
                if (recordIndex >= 0) {
                    this.records.splice(recordIndex, 1);
                }
                this._commands = this._commands.filter((c) => c[1] !== virtualId);
                this.count--;
                if (this._tmpIncreaseLimit > 0) {
                    this.model._patchConfig(this.config, {
                        limit: this.limit - 1,
                    });
                    this._tmpIncreaseLimit--;
                }
            }
        }
    }

    /**
     * Temporarily increase the page limit by ``n`` extra row slots (e.g. when
     * adding to an already-full page). Tracked in ``_tmpIncreaseLimit`` so
     * ``_discard`` can restore the original limit.
     *
     * @param {number} n
     */
    _bumpLimit(n) {
        this._tmpIncreaseLimit += n;
        this.model._patchConfig(this.config, { limit: this.limit + n });
    }

    /**
     * @param {RelationalRecord} record
     * @param {{ position?: string, sort?: boolean }} [options]
     */
    async _addRecord(record, { position, sort = true } = {}) {
        const command = [x2ManyCommands.CREATE, record._virtualId];
        if (position === "top") {
            this.records.unshift(record);
            if (this.records.length > this.limit) {
                this.records.pop();
            }
            this._currentIds.splice(this.offset, 0, record._virtualId);
            // Insert the CREATE just AFTER any leading SET/CLEAR command rather
            // than at index 0: a raw ``unshift`` puts CREATE before a SET (from
            // ``_replaceWith``), and the server applies commands in order — it
            // would create the row, then the SET/CLEAR replaces the whole
            // relation and drops it. With no SET/CLEAR the index is 0, i.e. the
            // previous unshift behaviour.
            let insertAt = 0;
            while (
                insertAt < this._commands.length &&
                (this._commands[insertAt][0] === x2ManyCommands.SET ||
                    this._commands[insertAt][0] === x2ManyCommands.CLEAR)
            ) {
                insertAt++;
            }
            this._commands.splice(insertAt, 0, command);
        } else if (position === "bottom") {
            this.records.push(record);
            this._currentIds.splice(this.offset + this.limit, 0, record._virtualId);
            if (this.records.length > this.limit) {
                this._bumpLimit(1);
            }
            this._commands.push(command);
        } else {
            const currentIds = [...this._currentIds, record._virtualId];
            if (this.orderBy.length && sort) {
                // ``sortRecords`` sorts ``currentIds`` and commits the SORTED
                // order into ``this._currentIds`` (via ``_load``). Do NOT
                // re-assign ``this._currentIds = currentIds`` here: that would
                // revert the just-committed sorted order back to insertion
                // order, desyncing ``_currentIds`` from the sorted ``records``.
                await sortRecords(this, currentIds);
            } else {
                if (this.records.length < this.limit) {
                    this.records.push(record);
                }
                this._currentIds = currentIds;
            }
            this._commands.push(command);
        }
        this.count++;
        this._needsReordering = true;
    }

    async _addNewRecordAtIndex(index, options = {}) {
        const newRecord = await this._createNewRecordDatapoint({
            context: options.context,
            manuallyAdded: true,
            mode: options.mode || "edit",
        });
        if (this.records.length === this.limit) {
            this._bumpLimit(1);
        }
        await this._addRecord(newRecord);
        // ``index`` may be out of range (e.g. account's section widget passes
        // ``sectionIndex - 1`` == -1 for a first section): a negative index
        // means "insert at the top" (no target → resequence to the first
        // position), an overflow clamps to the last record.
        const targetRecord =
            index >= 0
                ? this.records[Math.min(index, this.records.length - 1)]
                : undefined;
        await resequence(this, newRecord.id, targetRecord ? targetRecord.id : null);
        // resequence() sets dirty=true and _changes[handleField] via
        // record._update() (Invariant 1, record.js). The user hasn't touched
        // this new row, so force dirty=false, but keep _changes[handleField]
        // so it still ships with the parent's CREATE command on save (a
        // sanctioned invariant exception — see _assertChangeSetInvariant).
        newRecord.dirty = false;
        return newRecord;
    }

    _addSavePoint() {
        for (const id of Object.keys(this._cache)) {
            this._cache[id]._addSavePoint();
        }
        this._savePoint = markRaw({
            // Deep-copy each command tuple (and any inner array, e.g. a SET
            // command's id list at index 2): a shallow ``[...this._commands]``
            // shares the tuple objects by reference, so an in-place mutation
            // like ``absorbUnlinkIntoSet`` (which rewrites a SET tuple's id
            // array) would corrupt this snapshot too — and a later ``_discard``
            // would then restore a SET missing the unlinked id, silently
            // dropping that row from the next web_save.
            _commands: this._commands.map((c) =>
                c.map((el) => (Array.isArray(el) ? [...el] : el)),
            ),
            _currentIds: [...this._currentIds],
            count: this.count,
        });
    }

    _applyCommands(commands, options) {
        return applyCommands(this, commands, options);
    }

    /**
     * Merge a raw server value for this x2many field (a list of row objects,
     * bare ids, or commands) into the EXISTING list, preserving the pending
     * command log. Counterpart of ``record._applyValues`` for lists that
     * must not be rebuilt from scratch (a fresh StaticList has empty
     * ``_commands``): fresh row values are folded into the cache
     * (``_createRecordDatapoint`` merges into dirty cached records), and
     * displayed records whose clean datapoint was replaced are swapped in
     * place. Membership (``_currentIds``/``count``) is left to the pending
     * client state, which is authoritative while commands are staged.
     *
     * @param {any[]} serverValue
     */
    _applyServerValues(serverValue) {
        if (!Array.isArray(serverValue)) {
            return;
        }
        if (serverValue.length && Array.isArray(serverValue[0])) {
            // Command list — replay through the engine so UPDATE/LINK/…
            // merge into the pending state; possibly async (page-fill
            // loads), so track it like every other sync-chain application.
            this._trackCommandsPromise(this._applyCommands(serverValue));
            return;
        }
        for (const row of serverValue) {
            const data = typeof row === "number" ? { id: row } : row;
            const record = this._createRecordDatapoint(data);
            const index = this.records.findIndex((r) => r.resId === record.resId);
            if (index >= 0 && this.records[index] !== record) {
                this.records[index] = record;
            }
        }
    }

    /**
     * Track a floating ``_applyCommands`` result the caller can't await (the
     * call chain is synchronous: ``record._setData`` → ``parseServerValues``
     * → ``_applyCommands``). Chains onto ``_commandsPromise`` so flows needing
     * stable list state (save, discard's cache prune) can sequence after it;
     * rejections are logged and re-thrown in a microtask so the error service
     * still surfaces them, without breaking the chain for later followers.
     *
     * @param {Promise<void> | undefined} result
     */
    _trackCommandsPromise(result) {
        if (!result) {
            return;
        }
        const guarded = result.catch((error) => {
            console.error(
                `Failed to apply x2many commands (resModel: ${this.resModel}, list: ${this.id}): the pending record load rejected`,
            );
            // Re-throw outside this chain so the error service surfaces it
            // (error dialog / crash manager) instead of it being swallowed.
            Promise.resolve().then(() => {
                throw error;
            });
        });
        const combined = this._commandsPromise
            ? this._commandsPromise.then(() => guarded)
            : guarded;
        this._commandsPromise = combined;
        combined.then(() => {
            if (this._commandsPromise === combined) {
                this._commandsPromise = null;
            }
        });
    }

    _applyInitialCommands(commands) {
        this._trackCommandsPromise(this._applyCommands(commands));
        this._initialCommands = [...commands];
    }

    async _createNewRecordDatapoint(params = {}) {
        const changes = {};
        if (!params.withoutParent && this.config.relationField) {
            changes[this.config.relationField] = this._parent._getChanges();
            if (!this._parent.isNew) {
                changes[this.config.relationField].id = this._parent.resId;
            }
        }
        const values = await this.model._loadNewRecord(
            /** @type {any} */ ({
                resModel: this.resModel,
                activeFields: params.activeFields || this.activeFields,
                fields: this.fields,
                context: { ...this.context, ...params.context },
            }),
            /** @type {any} */ ({ changes, evalContext: this.evalContext }),
        );

        if (this.canResequence() && this.records.length) {
            const position = params.position || "bottom";
            const order = this.orderBy[0];
            const asc = !order || order.asc;
            let value;
            if (position === "top") {
                const isOnFirstPage = this.offset === 0;
                value = this.records[0].data[this.handleField];
                if (isOnFirstPage) {
                    if (asc) {
                        value = value > 0 ? value - 1 : 0;
                    } else {
                        value = value + 1;
                    }
                }
            } else if (position === "bottom") {
                value = this.records.at(-1).data[this.handleField];
                const isOnLastPage = this.limit + this.offset >= this.count;
                if (isOnLastPage) {
                    if (asc) {
                        value = value + 1;
                    } else {
                        value = value > 0 ? value - 1 : 0;
                    }
                }
            }
            values[this.handleField] = value;
        }
        return this._createRecordDatapoint(values, {
            mode: params.mode || "edit",
            virtualId: getId("virtual"),
            activeFields: params.activeFields,
            manuallyAdded: params.manuallyAdded,
        });
    }

    _createRecordDatapoint(data, params = {}) {
        const resId = data.id || false;
        if (!resId && !params.virtualId) {
            throw new Error("You must provide a virtualId if the record has no id");
        }
        const id = resId || params.virtualId;
        const cachedRecord = this._cache[id];
        if (
            cachedRecord &&
            (cachedRecord.dirty || Object.keys(cachedRecord._changes).length)
        ) {
            // A cached datapoint with pending ``_changes`` must not be replaced:
            // that would drop those changes and the ORM commands
            // ``serializeCommands`` derives from them. Hit by ``sort()``'s
            // restricted-field reload (only orderBy fields as activeFields).
            // Merge the fresh values in instead — ``_applyValues`` preserves
            // ``_changes`` (scalars untouched; x2many entries with pending
            // commands are merged via ``_applyServerValues``, not replaced)
            // and the record's fuller activeFields.
            cachedRecord._applyValues(data);
            return cachedRecord;
        }
        /** @type {any} */
        const config = {
            context: this.context,
            activeFields: { ...(params.activeFields || this.activeFields) },
            resModel: this.resModel,
            fields: params.fields || this.fields,
            relationField: this.config.relationField,
            resId,
            resIds: resId ? [resId] : [],
            mode: params.mode || "readonly",
            isMonoRecord: true,
        };
        const { CREATE, UPDATE } = x2ManyCommands;
        const options = {
            parentRecord: this._parent,
            onUpdate: async ({ withoutParentUpdate }) => {
                const id = record.isNew ? record._virtualId : record.resId;
                if (!this.currentIds.includes(id)) {
                    // the record hasn't been added to the list yet (we're currently creating it
                    // from a dialog)
                    return;
                }
                const hasCommand = this._commands.some(
                    (c) => (c[0] === CREATE || c[0] === UPDATE) && c[1] === id,
                );
                if (!hasCommand) {
                    this._commands.push([UPDATE, id]);
                }
                if (record._noUpdateParent) {
                    // the record is edited from a dialog, so we don't want to notify the parent
                    // record to be notified at each change inside the dialog (it will be notified
                    // at the end when the dialog is saved)
                    return;
                }
                if (!withoutParentUpdate) {
                    await this._onUpdate({
                        withoutOnchange: !record._checkValidity({
                            silent: true,
                        }),
                    });
                }
            },
            virtualId: params.virtualId,
            manuallyAdded: params.manuallyAdded,
        };
        const record = new this.model.Class.Record(this.model, config, data, options);
        this._cache[id] = record;
        if (!params.dontApplyCommands) {
            const commands = this._unknownRecordCommands[id];
            if (commands) {
                delete this._unknownRecordCommands[id];
                this._trackCommandsPromise(this._applyCommands(commands));
            }
        }
        return record;
    }

    _clearCommands() {
        this._commands = [];
        this._unknownRecordCommands = {};
        this._pruneCache();
    }

    /**
     * Remove cache entries for records no longer referenced by _currentIds.
     * Prevents unbounded cache growth during long editing sessions with
     * repeated add/delete cycles on x2many fields.
     *
     * Ids referenced by a live ``_savePoint`` are pinned: ``_clearCommands``
     * (the ``reload: false`` save path) runs this prune without clearing
     * savepoints, and a later ``_discard`` rebuilds ``records`` by mapping
     * the savepoint's ``_currentIds`` through ``_cache`` — an evicted entry
     * would leave a hole. ``_extendedRecords`` entries are dropped only for
     * evicted records: clearing it wholesale would force the next dialog
     * open on a still-cached record through ``extendRecord``'s
     * first-extension path again (an extra load RPC + ``_applyValues``).
     */
    _pruneCache() {
        const activeIds = new Set(this._currentIds);
        if (this._savePoint) {
            for (const id of this._savePoint._currentIds) {
                activeIds.add(id);
            }
        }
        for (const id of Object.keys(this._cache)) {
            if (!activeIds.has(id) && !activeIds.has(Number(id))) {
                this._extendedRecords.delete(this._cache[id].id);
                delete this._cache[id];
            }
        }
    }

    _discard() {
        for (const id of Object.keys(this._cache)) {
            this._cache[id]._discard();
        }
        if (this._savePoint) {
            this._commands = this._savePoint._commands;
            this._currentIds = this._savePoint._currentIds;
            this.count = this._savePoint.count;
        } else {
            this._commands = [];
            this._currentIds = [...this.resIds];
            this.count = this.resIds.length;
        }
        this._unknownRecordCommands = {};
        const limit = this.limit - this._tmpIncreaseLimit;
        this._tmpIncreaseLimit = 0;
        this.model._patchConfig(this.config, { limit });
        this.records = this._currentIds
            .slice(this.offset, this.offset + this.limit)
            .map((resId) => this._cache[resId]);
        if (!this._savePoint) {
            this._trackCommandsPromise(this._applyCommands(this._initialCommands));
            if (this._commandsPromise) {
                // A floating commands load is still mutating records/_cache, so
                // sequence the prune after it settles — otherwise it could evict
                // entries the load is about to (re)fill. Safe: the tracked
                // promise never rejects (see _trackCommandsPromise) and prune
                // re-reads _currentIds at execution time.
                this._commandsPromise.then(() => this._pruneCache());
            } else {
                this._pruneCache();
            }
        }
        this._savePoint = undefined;
    }

    /**
     * @fixme: this method is naive and ineffective (it triggers a lot of onchange rpcs)
     */
    async _duplicateRecords(records, options) {
        // No records to duplicate, or no handle field to sequence on: the
        // sequence arithmetic below would read `records[-1]`/`data[undefined]`
        // and write NaN sequences into every following record.
        if (!records.length || !this.handleField) {
            return;
        }
        const targetIndex = Math.min(
            Math.max(
                options.targetIndex ?? this.records.indexOf(records.at(-1)) + 1,
                0,
            ),
            this.records.length,
        );
        const copyFields = options.copyFields || [];
        // targetIndex 0 (insert at the top — e.g. account's section duplicate)
        // starts from the first record's sequence instead of reading the
        // non-existent records[-1].
        let sequence =
            targetIndex > 0
                ? this.records[targetIndex - 1].data[this.handleField] + 1
                : this.records[0].data[this.handleField];
        const newRecords = await Promise.all(
            records.map(async () =>
                this._createNewRecordDatapoint({
                    mode: "readonly",
                }),
            ),
        );
        await Promise.all(
            records.map((record, index) =>
                newRecords[index]._update({
                    ...copyRecordData(record, copyFields),
                    [this.handleField]: sequence++,
                }),
            ),
        );

        const localIncreaseLimit = this.records.length + records.length - this.limit;
        if (localIncreaseLimit > 0) {
            this._bumpLimit(localIncreaseLimit);
        }

        const commands = [];
        // `this.records.slice(targetIndex)` is wrong
        // we need to iterate on ALL the next records even the ones on the next pages..
        for (const record of this.records.slice(targetIndex)) {
            commands.push(
                x2ManyCommands.update(record.resId || record._virtualId, {
                    [this.handleField]: sequence++,
                }),
            );
        }
        await this._applyCommands(commands);

        await Promise.all(
            newRecords.map((record) => this._addRecord(record, { sort: false })),
        );

        await sortRecords(this);
    }

    /** @param {{ withReadonly?: boolean }} [options] */
    _getCommands({ withReadonly } = {}) {
        return serializeCommands(this._commands, {
            unknownRecordCommands: this._unknownRecordCommands,
            fields: this.fields,
            activeFields: this.activeFields,
            context: this.context,
            withReadonly,
            getRecord: (id) => this._cache[id],
            getRecordChanges: (record, wr) =>
                record._getChanges(record._changes, { withReadonly: wr }),
            convertUnityValues: fromUnityToServerValues,
        });
    }

    _getResIdsToLoad(resIds, fieldNames = this.fieldNames) {
        // Filter "id" once — not inside the per-record callback
        const relevantFields = fieldNames.filter((f) => f !== "id");
        return resIds.filter((resId) => {
            if (typeof resId === "string") {
                // this is a virtual id, we don't want to read it
                return false;
            }
            const record = this._cache[resId];
            if (!record) {
                // record hasn't been loaded yet
                return true;
            }
            // Test against the fields whose values were actually fetched
            // (``_loadedFieldNames``), not ``record.fieldNames``: the latter
            // derives from ``activeFields`` (what the view wants) and is
            // already complete on a stub datapoint created from a bare
            // ``{id}`` (e.g. a LINK command applied while the page was
            // full), which would classify the stub as loaded and render a
            // row of default values after a page navigation.
            return relevantFields.some(
                (fieldName) => !record._loadedFieldNames.has(fieldName),
            );
        });
    }

    async _load({
        limit = this.limit,
        offset = this.offset,
        orderBy = this.orderBy,
        nextCurrentIds = this._currentIds,
    } = {}) {
        const currentIds = nextCurrentIds.slice(offset, offset + limit);
        const resIds = this._getResIdsToLoad(currentIds);
        if (resIds.length) {
            const records = await this.model._loadRecords(
                { ...this.config, resIds },
                this.evalContext,
            );
            for (const record of records) {
                this._createRecordDatapoint(record);
            }
        }
        this.records = currentIds.map((id) => this._cache[id]);
        this._currentIds = nextCurrentIds;
        this.model._patchConfig(this.config, { limit, offset, orderBy });
    }

    async _replaceWith(ids, { reload = false } = {}) {
        const resIds = reload ? ids : ids.filter((id) => !this._cache[id]);
        if (resIds.length) {
            const records = await this.model._loadRecords({
                ...this.config,
                resIds,
                context: this.context,
            });
            for (const record of records) {
                this._createRecordDatapoint(record);
            }
        }
        this.records = ids.map((id) => this._cache[id]);
        const idSet = new Set(ids);
        const updateCommandsToKeep = this._commands.filter(
            (c) => c[0] === x2ManyCommands.UPDATE && idSet.has(c[1]),
        );
        this._commands = [x2ManyCommands.set(ids), ...updateCommandsToKeep];
        this._currentIds = [...ids];
        this.count = this._currentIds.length;
        if (this._currentIds.length > this.limit) {
            this._bumpLimit(this._currentIds.length - this.limit);
        }
    }

    _updateContext(context) {
        // Runs from the parent's ``_setEvalContext`` for EVERY x2many field on
        // EVERY committed edit. Skipping when the field context is unchanged
        // avoids an O(rows × fields) recompute per keystroke; safe because
        // sub-records observe the parent LIVE via the ``parent`` getter
        // (record.js), not through this recompute, and an unchanged recompute
        // would produce identical values anyway (OWL drops the no-op render).
        //
        // Compare by VALUE (``deepEqual``), not reference: ``getFieldContext()``
        // always allocates fresh arrays (e.g. ``allowed_company_ids``), so
        // ``!==`` would never skip. Compare over the UNION of old + new keys so
        // a key that DISAPPEARED (not just changed) is still detected.
        let changed = false;
        const keys = new Set([...Object.keys(this.context), ...Object.keys(context)]);
        for (const key of keys) {
            if (!deepEqual(this.context[key], context[key])) {
                changed = true;
                break;
            }
        }
        if (!changed) {
            return;
        }
        // ``this.context`` mirrors getFieldContext() exactly (it has no other
        // contributor — see the ``getFieldContext`` loop in ``record.js``), so drop keys that disappeared before
        // merging; a plain Object.assign would leave stale keys lingering in
        // every sub-record's eval context (and in load/save RPCs).
        for (const key of Object.keys(this.context)) {
            if (!(key in context)) {
                delete this.context[key];
            }
        }
        Object.assign(this.context, context);
        for (const record of Object.values(this._cache)) {
            record._setEvalContext();
        }
    }
}
