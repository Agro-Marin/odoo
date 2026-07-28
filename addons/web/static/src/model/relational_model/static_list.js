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
import { fromUnityToServerValues, invalidateAggregateSpecs } from "./field_values.js";
import { invalidateModifierDependencies } from "./record_utils.js";
import { applyCommands } from "./static_list_command_engine.js";
import { resequence, sort as sortRecords, sortBy } from "./static_list_sort.js";
import { copyRecordData } from "./static_list_utils.js";

/** @import { RelationalRecord } from "./record.js" */

/**
 * Deep-copy a command log one level into each tuple's array elements (a SET's
 * id list is the only nested mutable member), so a snapshot survives the
 * in-place splices ``absorbUnlinkIntoSet`` performs on staged commands.
 *
 * @param {[number, any, any?][]} commands
 * @returns {[number, any, any?][]}
 */
function cloneCommands(commands) {
    return commands.map((c) => c.map((el) => (Array.isArray(el) ? [...el] : el)));
}

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
        this._unknownRecordCommands = {};
        this._loadingStubIds = new Set();
        this._currentIds = [...this.resIds];
        this._needsReordering = false;
        this._tmpIncreaseLimit = 0;
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
            completeActiveFields(this.config.activeFields, params.activeFields);
            invalidateModifierDependencies(this.config.activeFields);
            Object.assign(this.fields, params.fields);
            invalidateAggregateSpecs(this.fields);
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
                    fields: this.fields,
                };

                if (this._extendedRecords.has(record.id)) {
                    this.model._patchConfig(record.config, config);
                    record._addSavePoint();
                    return record;
                }
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
                    await this._applyCommands(commands);
                }
                record._addSavePoint();
            } else {
                record = await this._createNewRecordDatapoint({
                    activeFields,
                    context: params.context,
                    withoutParent: params.withoutParent,
                    manuallyAdded: true,
                });
                record._activeFieldsToRestore = { ...this.config.activeFields };
                record._noUpdateParent = true;
            }
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
        if (this.model.urgentSave.isActive) {
            return this._leaveEditMode({ discard, canAbandon, validate });
        }
        if (this.editedRecord) {
            await this.model._askChanges();
        }
        return this.model.mutex.exec(() =>
            this._leaveEditMode({ discard, canAbandon, validate }),
        );
    }

    /**
     * Core of {@link leaveEditMode}. Runs under ``model.mutex`` (or directly on
     * the urgent tab-close path), so it uses only synchronous ``_``-prefixed
     * record internals; pending edits are flushed by the caller's
     * ``_askChanges`` prelude.
     *
     * @param {{ discard?: boolean, canAbandon?: boolean, validate?: boolean }} [options]
     * @returns {Promise<boolean>} whether edit mode was left
     */
    async _leaveEditMode({ discard, canAbandon, validate } = {}) {
        let editedRecord = this.editedRecord;
        if (editedRecord) {
            const isValid = editedRecord._checkValidity();
            if (!isValid && validate) {
                return false;
            }
            if (canAbandon !== false && !validate) {
                this._abandonRecords([editedRecord], { force: true });
            }
            editedRecord = this.editedRecord;
            if (editedRecord) {
                if (isValid && !editedRecord.dirty && discard) {
                    return false;
                }
                if (isValid || (!editedRecord.dirty && !editedRecord._manuallyAdded)) {
                    editedRecord._switchMode("readonly");
                }
            }
        }
        return !this.editedRecord;
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
                await this._addRecord(record);
            } else if (!record.dirty) {
                return;
            }
            await this._onUpdate();
            record._restoreActiveFields();
            record._savePoint = undefined;
        });
    }

    /**
     * Snapshot the data needed to map a just-created record's ``_virtualId`` to
     * its server-assigned resId AFTER a parent save. Must be called BEFORE the
     * save (which clears the CREATE commands and assigns resIds). Encapsulates
     * the create-order correlation so consumers (``x2many_field.switchToForm``)
     * don't reach into the private command log / resIds cross-layer.
     *
     * @returns {{ createVirtualIds: (number|string)[], previousResIds: Set<any> }}
     */
    snapshotCreateReconciliation() {
        return {
            createVirtualIds: this._commands
                .filter(([command]) => command === x2ManyCommands.CREATE)
                .map(([, virtualId]) => virtualId),
            previousResIds: new Set(this.resIds),
        };
    }

    /**
     * Resolve the resId the last save assigned to ``record``, using a token from
     * ``snapshotCreateReconciliation`` taken before that save.
     *
     * The nth CREATE command maps to the nth new resId in ASCENDING ID ORDER,
     * not to the nth id as returned: ids come from a Postgres sequence, so a
     * single save's inserts are monotonically increasing in creation order,
     * which survives the server reordering rows on the way back.
     *
     * Returns ``undefined`` — so callers surface "save first" rather than open
     * some other record — whenever the mapping cannot be trusted: a row-count
     * mismatch (a ``create()`` override inserting extra rows, interleaved ids),
     * or a record that no CREATE command claims. The latter means the record is
     * not one this save created, and the previous fallback of returning the
     * highest new id would then have navigated to an unrelated record.
     *
     * @param {{ createVirtualIds: (number|string)[], previousResIds: Set<any> }} token
     * @param {RelationalRecord} record
     * @returns {number|undefined}
     */
    resolveCreatedResId(token, record) {
        const newResIds = this.resIds.filter((id) => !token.previousResIds.has(id));
        if (newResIds.length !== token.createVirtualIds.length) {
            return undefined;
        }
        const index = token.createVirtualIds.indexOf(record._virtualId);
        if (index < 0) {
            return undefined;
        }
        return [...newResIds].sort((x, y) => x - y)[index];
    }

    _abandonRecords(
        records = this.records,
        /** @type {{ force?: boolean }} */ { force } = {},
    ) {
        for (const record of records) {
            if (record.canBeAbandoned && (force || !record._checkValidity())) {
                const virtualId = record._virtualId;
                const idIndex = this._currentIds.findIndex((id) => id === virtualId);
                if (idIndex < 0) {
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
     * Pull ``offset`` back into range after the membership shrank below the
     * current page start.
     *
     * ``records`` is a window into ``_currentIds`` pinned by ``offset``, so a
     * batch that removes every id at or after that offset (an onchange
     * answering with a shorter relation, a bulk unlink) leaves the window
     * past the end: ``_currentIds``/``count`` are right but the x2many renders
     * an empty page until the user paginates back by hand. Lands on the last
     * page that still holds data — 0 for an empty list — mirroring the offset
     * reset ``_loadData`` already does for server-backed lists.
     */
    _clampOffset() {
        const length = this._currentIds.length;
        if (this.offset === 0 || this.offset < length) {
            return;
        }
        const limit = this.limit;
        const offset =
            length && limit > 0 ? Math.floor((length - 1) / limit) * limit : 0;
        this.model._patchConfig(this.config, { offset });
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
        const targetRecord =
            index >= 0
                ? this.records[Math.min(index, this.records.length - 1)]
                : undefined;
        await resequence(this, newRecord.id, targetRecord ? targetRecord.id : null);
        newRecord.dirty = false;
        return newRecord;
    }

    /**
     * Capture every piece of mutable state ``_applyCommands`` (and the
     * ``_replaceWith`` path it shares with ``preprocessX2manyChanges``) can
     * touch, so a caller that must undo a half-applied batch can put the list
     * back exactly as it found it.
     *
     * The set is deliberately wider than membership: ``_bumpLimit`` widens
     * ``config.limit`` AND ``_tmpIncreaseLimit``, and an UPDATE naming a record
     * on an unloaded page stashes its payload in ``_unknownRecordCommands``.
     * A restore that skipped those left the page one row too tall and left an
     * orphaned stash that a later legitimate ``[UPDATE, id]`` re-attached to
     * the save payload (see static_list_rollback_completeness.test.js).
     *
     * ``_cache`` is NOT captured: entries are keyed by id and merged into, so
     * re-creating one is idempotent, and pinning them would defeat
     * ``_pruneCache``.
     *
     * @returns {Record<string, any>} single-use snapshot for {@link _restore}
     */
    _snapshot() {
        return markRaw({
            _commands: cloneCommands(this._commands),
            _currentIds: [...this._currentIds],
            count: this.count,
            _unknownRecordCommands: Object.fromEntries(
                Object.entries(this._unknownRecordCommands).map(([id, cmds]) => [
                    id,
                    cloneCommands(cmds),
                ]),
            ),
            _loadingStubIds: new Set(this._loadingStubIds),
            _tmpIncreaseLimit: this._tmpIncreaseLimit,
            limit: this.limit,
        });
    }

    /**
     * Reinstate a {@link _snapshot}. Copies the snapshot's containers rather
     * than aliasing them, so one snapshot can be restored more than once (the
     * undo closure in ``record._applyChanges`` is handed out to callers that
     * may or may not invoke it).
     *
     * ``records`` is rebuilt from the restored membership; ids whose datapoint
     * was evicted in the meantime (``_replaceWith`` prunes the cache) are
     * dropped rather than left as holes — ``ListGridState._materialize``
     * dereferences every entry, same guard as ``_load``.
     *
     * @param {Record<string, any>} snapshot
     */
    _restore(snapshot) {
        this._commands = cloneCommands(snapshot._commands);
        this._currentIds = [...snapshot._currentIds];
        this.count = snapshot.count;
        this._unknownRecordCommands = Object.fromEntries(
            Object.entries(snapshot._unknownRecordCommands).map(([id, cmds]) => [
                id,
                cloneCommands(cmds),
            ]),
        );
        this._loadingStubIds.clear();
        for (const id of snapshot._loadingStubIds) {
            this._loadingStubIds.add(id);
        }
        this._tmpIncreaseLimit = snapshot._tmpIncreaseLimit;
        if (this.limit !== snapshot.limit) {
            this.model._patchConfig(this.config, { limit: snapshot.limit });
        }
        this.records = this._currentIds
            .slice(this.offset, this.offset + this.limit)
            .map((resId) => this._cache[resId])
            .filter(Boolean);
    }

    _addSavePoint() {
        for (const id of Object.keys(this._cache)) {
            this._cache[id]._addSavePoint();
        }
        this._savePoint = this._snapshot();
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
            cachedRecord._applyValues(data);
            return cachedRecord;
        }
        /** @type {any} */
        const config = {
            context: this.context,
            activeFields: params.activeFields || this.activeFields,
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
                    return;
                }
                const hasCommand = this._commands.some(
                    (c) => (c[0] === CREATE || c[0] === UPDATE) && c[1] === id,
                );
                if (!hasCommand) {
                    this._commands.push([UPDATE, id]);
                }
                if (record._noUpdateParent) {
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
        this._loadingStubIds.clear();
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
        for (const id of this.resIds) {
            activeIds.add(id);
        }
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
            // Restore what the savepoint captured — page limit included. The
            // shared tail this branch used to fall through stripped the WHOLE
            // ``_tmpIncreaseLimit``, which also gave back row slots opened
            // BEFORE the savepoint: reverting a form dialog then paged out
            // rows the savepoint still lists in ``_currentIds``.
            const savePoint = this._savePoint;
            this._savePoint = undefined;
            this._restore(savePoint);
            return;
        }
        this._commands = [];
        this._currentIds = [...this.resIds];
        this.count = this.resIds.length;
        this._unknownRecordCommands = {};
        this._loadingStubIds.clear();
        // No savepoint: the list goes back to server truth, so every temporary
        // slot is forfeit whenever it was opened.
        const limit = this.limit - this._tmpIncreaseLimit;
        this._tmpIncreaseLimit = 0;
        this.model._patchConfig(this.config, { limit });
        this.records = this._currentIds
            .slice(this.offset, this.offset + this.limit)
            .map((resId) => this._cache[resId])
            .filter(Boolean);
        this._trackCommandsPromise(this._applyCommands(this._initialCommands));
        if (this._commandsPromise) {
            this._commandsPromise.then(() => this._pruneCache());
        } else {
            this._pruneCache();
        }
    }

    /**
     * @fixme: this method is naive and ineffective (it triggers a lot of onchange rpcs)
     */
    async _duplicateRecords(records, options) {
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
        const relevantFields = fieldNames.filter((f) => f !== "id");
        return resIds.filter((resId) => {
            if (typeof resId === "string") {
                return false;
            }
            const record = this._cache[resId];
            if (!record) {
                return true;
            }
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
        if (this.records.includes(undefined)) {
            const missing = new Set(currentIds.filter((id) => !this._cache[id]));
            this.records = this.records.filter(Boolean);
            nextCurrentIds = nextCurrentIds.filter((id) => !missing.has(id));
        }
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
        // ``_loadRecords`` only throws when NO row comes back; a partial
        // response (an id deleted or made inaccessible server-side between the
        // SET being built and this load) simply returns fewer. Mapping every
        // requested id through ``_cache`` would then leave ``undefined`` holes
        // in ``records`` — which ``ListGridState._materialize`` dereferences —
        // and keep the phantom id in ``_currentIds``/``count`` and in the SET
        // command the next save ships. Same guard as ``_load``.
        const presentIds = ids.filter((id) => this._cache[id]);
        this.records = presentIds.map((id) => this._cache[id]);
        const idSet = new Set(presentIds);
        const updateCommandsToKeep = this._commands.filter(
            (c) => c[0] === x2ManyCommands.UPDATE && idSet.has(c[1]),
        );
        this._commands = [x2ManyCommands.set(presentIds), ...updateCommandsToKeep];
        this._currentIds = [...presentIds];
        this.count = this._currentIds.length;
        for (const id of Object.keys(this._unknownRecordCommands)) {
            if (!idSet.has(id) && !idSet.has(Number(id))) {
                delete this._unknownRecordCommands[id];
            }
        }
        for (const id of [...this._loadingStubIds]) {
            if (!idSet.has(id) && !idSet.has(Number(id))) {
                this._loadingStubIds.delete(id);
            }
        }
        this._pruneCache();
        if (this._currentIds.length > this.limit) {
            this._bumpLimit(this._currentIds.length - this.limit);
        }
    }

    _updateContext(context) {
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
