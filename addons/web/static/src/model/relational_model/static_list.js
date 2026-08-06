// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/static_list */

import { markRaw } from "@odoo/owl";
import { reportUncaught } from "@web/core/errors/error_utils";
import { deepEqual, omit } from "@web/core/utils/collections/objects";

import { serializeCommands } from "./command_builder.js";
import { x2ManyCommands } from "./commands.js";
import { DataPoint } from "./datapoint.js";
import { getId, getSpecEvalContext, isX2Many } from "./field_context.js";
import {
    cloneActiveFields,
    completeActiveFields,
    patchActiveFields,
} from "./field_metadata.js";
import { fromUnityToServerValues, invalidateAggregateSpecs } from "./field_values.js";
import { ListMembership } from "./list_membership.js";
import { applyCommands } from "./static_list_command_engine.js";
import { resequence, sort as sortRecords, sortBy } from "./static_list_sort.js";
import { copyRecordData, listId, pairCreatedRows } from "./static_list_utils.js";

/** @import { DatapointId } from "@web/model/types" */
/** @import { RelationalRecord } from "./record.js" */

/**
 * @param {[number, any, any?][]} commands
 * @returns {[number, any, any?][]}
 */
function cloneCommands(commands) {
    return /** @type {[number, any, any?][]} */ (
        commands.map((c) => c.map((el) => (Array.isArray(el) ? [...el] : el)))
    );
}

/** @param {Record<string, [number, any, any?][]>} byId */
function cloneCommandsById(byId) {
    return Object.fromEntries(
        Object.entries(byId).map(([id, cmds]) => [id, cloneCommands(cmds)]),
    );
}

/**
 * @type {Record<string, { clone: (value: any) => any, restore?: (list: any, value: any) => void }>}
 */
const RESTORABLE_STATE = {
    _commands: { clone: cloneCommands },
    _currentIds: { clone: (ids) => [...ids] },
    _unknownRecordCommands: { clone: cloneCommandsById },
    _loadingStubIds: {
        clone: (ids) => new Set(ids),
        restore: (list, ids) => {
            list._loadingStubIds.clear();
            for (const id of ids) {
                list._loadingStubIds.add(id);
            }
        },
    },
    _tmpIncreaseLimit: { clone: (n) => n },
    _needsReordering: { clone: (flag) => flag },
};

const RESTORABLE_CONFIG_KEYS = ["limit", "offset"];

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
         * @type {Promise<void> | null}
         */
        this._commandsPromise = null;
        this._savePoint = undefined;
        this._unknownRecordCommands = {};
        this._loadingStubIds = new Set();
        /**
         * A tracked command replay rejected: some rows may be left as `{id}`
         * stubs with no display data. Read by `_healFailedReplay` after the
         * next successful save. @type {boolean}
         */
        this._replayFailed = false;
        /**
         * @type {ListMembership}
         */
        this._membership = new ListMembership(this.resIds);
        this._needsReordering = false;
        this._extendedRecords = new Set();

        this.records = data
            .slice(this.offset, this.offset + this.limit)
            .map((r) => this._createRecordDatapoint(r));
        this.handleField = Object.keys(this.activeFields).find(
            (fieldName) => this.activeFields[fieldName].isHandle,
        );
    }

    /** @type {RelationalRecord[]} */
    get records() {
        return this._membership.records;
    }

    set records(records) {
        this._membership.records = records;
    }

    /**
     * Derived from `_currentIds` -- see {@link ListMembership}. There is no
     * setter: membership changes by inserting into or removing from
     * `_currentIds`, and the total follows.
     */
    get count() {
        return this._membership.count;
    }

    get _currentIds() {
        return this._membership.ids;
    }

    set _currentIds(ids) {
        this._membership.ids = ids;
    }

    get _tmpIncreaseLimit() {
        return this._membership.tmpIncreaseLimit;
    }

    set _tmpIncreaseLimit(n) {
        this._membership.tmpIncreaseLimit = n;
    }

    get currentIds() {
        return this._currentIds;
    }

    get editedRecord() {
        return this.records.find((record) => record.isInEdition);
    }

    get evalContext() {
        /** @type {any} */
        const evalContext = getSpecEvalContext(this.config);
        if (this._parent) {
            evalContext.parent = this._parent.evalContext;
        }
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
     * The three questions the save path asks of a list. Published so the
     * traversal in x2many_tree.js can answer them without reaching into
     * `_cache` / `_commands` / `_commandsPromise`.
     *
     * @returns {Promise<void> | null} in-flight command replay, if any
     */
    get pendingCommands() {
        return this._commandsPromise;
    }

    /** @returns {RelationalRecord[]} every datapoint this list has built */
    get cachedRecords() {
        return Object.values(this._cache);
    }

    /** @returns {boolean} */
    get hasStagedCommands() {
        return this._commands.length > 0;
    }

    /**
     * @param {DatapointId} id
     * @returns {RelationalRecord | undefined}
     */
    getCachedRecord(id) {
        return this._cache[id];
    }

    /**
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
            await this._applyCommands([x2ManyCommands.delete(listId(record))]);
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
     * Build the record's active-field set from the extension request, merged
     * over this list's own active fields: the request's fields win, and any
     * this list already tracks but the request omits are carried through.
     *
     * @param {{ activeFields: Object, fields: Object }} params
     * @returns {Object}
     */
    _mergeExtensionActiveFields(params) {
        const activeFields = cloneActiveFields(params.activeFields);
        completeActiveFields(this.config.activeFields, activeFields);
        Object.assign(this.fields, params.fields);
        invalidateAggregateSpecs(this.fields);
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
        return activeFields;
    }

    /**
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
            const activeFields = this._mergeExtensionActiveFields(params);
            if (record) {
                record.extendActiveFields(this.config.activeFields);
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
                record.extendActiveFields(this.config.activeFields);
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
     * @param {{ discard?: boolean, canAbandon?: boolean, validate?: boolean }} [options]
     * @returns {Promise<boolean>}
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
     * @param {RelationalRecord} record
     */
    validateExtendedRecord(record) {
        return this.model.mutex.exec(async () => {
            if (!this._currentIds.includes(listId(record))) {
                await this._addRecord(record);
            } else if (!record.hasPendingChanges) {
                // Deliberate, not an oversight: a row confirmed without a
                // single edit KEEPS the widened active fields the dialog gave
                // it. Narrowing them back to the list's columns makes the next
                // onchange payload for a sub-form-only x2many fail the
                // `fieldName in record.activeFields` test in the command
                // engine, which defers it into `_unknownRecordCommands` -- and
                // `extendRecord` only replays those the FIRST time a row is
                // extended, so reopening the dialog shows the pre-onchange
                // value forever. Covered by one2many_field.test.js, "onchange
                // specification complete after open sub form view not inline".
                return;
            }
            await this._onUpdate();
            record._restoreActiveFields();
            record._savePoint = undefined;
        });
    }

    /**
     * @returns {(number|string)[]}
     */
    _createCommandVirtualIds() {
        return this._commands
            .filter(([command]) => command === x2ManyCommands.CREATE)
            .map(([, virtualId]) => virtualId);
    }

    /**
     * @returns {{ createVirtualIds: (number|string)[], previousResIds: Set<any> }}
     */
    snapshotCreateReconciliation() {
        return {
            createVirtualIds: this._createCommandVirtualIds(),
            previousResIds: new Set(this.resIds),
        };
    }

    /**
     * @param {{ createVirtualIds: (number|string)[], previousResIds: Set<any> }} token
     * @param {RelationalRecord} record
     * @returns {number|undefined}
     */
    resolveCreatedResId(token, record) {
        const pairs = pairCreatedRows(
            token.createVirtualIds,
            this.resIds.filter((id) => !token.previousResIds.has(id)),
        );
        return pairs?.get(listId(record));
    }

    _abandonRecords(
        records = this.records,
        /** @type {{ force?: boolean }} */ { force } = {},
    ) {
        for (const record of records) {
            if (record.canBeAbandoned && (force || !record._checkValidity())) {
                const virtualId = listId(record);
                if (!this._membership.removeMember(virtualId, record)) {
                    continue;
                }
                this._commands = this._commands.filter((c) => c[1] !== virtualId);
                if (this._tmpIncreaseLimit > 0) {
                    this.model._patchConfig(this.config, {
                        limit: this.limit - 1,
                    });
                    this._tmpIncreaseLimit--;
                }
            }
        }
    }

    _clampOffset() {
        const offset = this._membership.clampedOffset(this.offset, this.limit);
        if (offset !== null) {
            this.model._patchConfig(this.config, { offset });
        }
    }

    _materializeWindow() {
        return this._membership.materialize(this._cache, this.offset, this.limit);
    }

    /**
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
        const virtualId = record._virtualId;
        if (position === "top" || position === "bottom") {
            // Interactive editable-list add. The record is already a cached
            // datapoint, so the engine's CREATE handler echoes it and owns the
            // window insertion for both ends (see `applyCreate`) -- one command
            // interpreter instead of a parallel splice here.
            await this._applyCommands([[x2ManyCommands.CREATE, virtualId]], {
                position,
            });
        } else {
            // Non-editable / programmatic add: append to the relation, respect
            // the page (only push into the window when it is not full), and sort
            // when the list is ordered.
            const currentIds = [...this._currentIds, listId(record)];
            if (this.orderBy.length && sort) {
                await sortRecords(this, currentIds);
            } else {
                if (this.records.length < this.limit) {
                    this.records.push(record);
                }
                this._currentIds = currentIds;
            }
            this._commands.push([x2ManyCommands.CREATE, virtualId]);
        }
        this._needsReordering = true;
    }

    /**
     * Cleared by the sort helper once it has applied the reorder-load for the
     * pending-reorder flag {@link _addRecord} raises when a record is inserted
     * out of order. Published so the helper need not write the private.
     */
    markReordered() {
        this._needsReordering = false;
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
     * @returns {Record<string, any>}
     */
    _snapshot() {
        /** @type {Record<string, any>} */
        const snapshot = { config: {} };
        for (const [key, { clone }] of Object.entries(RESTORABLE_STATE)) {
            snapshot[key] = clone(this[key]);
        }
        for (const key of RESTORABLE_CONFIG_KEYS) {
            snapshot.config[key] = this[key];
        }
        return markRaw(snapshot);
    }

    /**
     * @param {Record<string, any>} snapshot
     */
    _restore(snapshot) {
        for (const [key, { clone, restore }] of Object.entries(RESTORABLE_STATE)) {
            const value = clone(snapshot[key]);
            if (restore) {
                restore(this, value);
            } else {
                this[key] = value;
            }
        }
        /** @type {Record<string, any>} */
        const patch = {};
        for (const key of RESTORABLE_CONFIG_KEYS) {
            if (this[key] !== snapshot.config[key]) {
                patch[key] = snapshot.config[key];
            }
        }
        if (Object.keys(patch).length) {
            this.model._patchConfig(this.config, patch);
        }
        this._materializeWindow();
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
     * @param {any[]} serverValue
     */
    _applyServerValues(serverValue) {
        if (!Array.isArray(serverValue)) {
            return;
        }
        if (serverValue.length && Array.isArray(serverValue[0])) {
            this.stageCommands(serverValue);
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
     * Apply commands AND register the replay on this list's barrier, as one
     * step. `_applyCommands` only returns a promise when it has records to
     * load, and applying without registering that promise is precisely what a
     * concurrent save races: `waitForPendingCommands` finds nothing to wait on
     * and the `web_save` goes out mid-replay. Callers outside this file should
     * use this rather than pairing the two by hand.
     *
     * @param {[number, any, any?][]} commands
     * @param {{ canAddOverLimit?: boolean }} [options]
     */
    stageCommands(commands, options) {
        this._trackCommandsPromise(this._applyCommands(commands, options));
    }

    /**
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
            // The failed load may have left `{id}` stubs on the page. Do not
            // block anything here (a save must still proceed); just remember,
            // so `_healFailedReplay` re-fetches them once the server answers
            // a save again.
            this._replayFailed = true;
            reportUncaught(error);
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
        this.stageCommands(commands);
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
        if (cachedRecord?.hasPendingChanges) {
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
                const id = listId(record);
                if (!this.currentIds.includes(id)) {
                    return;
                }
                const hasCommand = this._commands.some(
                    (c) => (c[0] === CREATE || c[0] === UPDATE) && c[1] === id,
                );
                if (!hasCommand) {
                    this._commands.push([UPDATE, id]);
                }
                if (record.skipsParentUpdate) {
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
                this.stageCommands(commands);
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
     * @param {(number | Record<string, any>)[]} serverValue
     */
    _commitSave(serverValue) {
        if (!Array.isArray(serverValue)) {
            this._clearCommands();
            return;
        }
        const serverIds = serverValue.map((v) =>
            v && typeof v === "object" ? v.id : v,
        );
        const previousResIds = new Set(this.resIds);
        const pairs = pairCreatedRows(
            this._createCommandVirtualIds(),
            serverIds.filter((id) => !previousResIds.has(id)),
            { clientIds: this._currentIds, serverIds },
        );
        for (const [virtualId, resId] of pairs || []) {
            this._rekeyCreatedRow(virtualId, resId);
        }
        const confirmed = new Set(serverIds);
        const kept = this._currentIds.filter((id) => confirmed.has(id));
        const keptSet = new Set(kept);
        this._currentIds = [...kept, ...serverIds.filter((id) => !keptSet.has(id))];
        this.model._patchConfig(this.config, { resIds: [...serverIds] });
        this._commands = [];
        this._initialCommands = [];
        this._unknownRecordCommands = {};
        this._loadingStubIds.clear();
        this._tmpIncreaseLimit = 0;
        this._savePoint = undefined;
        this._materializeWindow();
        this._pruneCache();
        // `_healMissingWindow` re-fetches every under-loaded window row, which
        // subsumes whatever a failed replay left behind.
        this._replayFailed = false;
        this._healMissingWindow();
    }

    /**
     * A command replay rejected earlier (see `_trackCommandsPromise`): the
     * commands themselves were staged, so the save payload was right, but the
     * record loads they carried never landed and some rows may still be `{id}`
     * stubs. Called by the save path once a save has succeeded — the server is
     * answering again — to re-fetch those rows so the display converges with
     * what was saved. The load is tracked, so a subsequent save waits on it.
     */
    _healFailedReplay() {
        if (!this._replayFailed) {
            return;
        }
        this._replayFailed = false;
        this._healMissingWindow();
    }

    /**
     * @param {string | number} virtualId
     * @param {number} resId
     */
    _rekeyCreatedRow(virtualId, resId) {
        const record = this._cache[virtualId];
        if (!record) {
            return;
        }
        delete this._cache[virtualId];
        record.assignResId(resId);
        this._cache[resId] = record;
        const index = this._currentIds.indexOf(virtualId);
        if (index >= 0) {
            this._currentIds[index] = resId;
        }
    }

    _healMissingWindow() {
        const windowIds = this._currentIds.slice(this.offset, this.offset + this.limit);
        const missingIds = this._getResIdsToLoad(windowIds);
        if (!missingIds.length) {
            return;
        }
        this._trackCommandsPromise(
            (async () => {
                const records = await this.model._loadRecords(
                    { ...this.config, resIds: missingIds },
                    this.evalContext,
                );
                for (const record of records) {
                    this._createRecordDatapoint(record);
                }
                this._materializeWindow();
            })(),
        );
    }

    _pruneCache() {
        const pinnedIds = this._collectPinnedIds();
        for (const id of Object.keys(this._cache)) {
            if (!pinnedIds.has(id) && !pinnedIds.has(Number(id))) {
                this._extendedRecords.delete(this._cache[id].id);
                delete this._cache[id];
            }
        }
    }

    /**
     * @returns {Set<DatapointId>}
     */
    _collectPinnedIds() {
        /** @type {Set<DatapointId>} */
        const pinnedIds = new Set();
        for (const id of this._currentIds) {
            pinnedIds.add(id);
        }
        for (const id of this.resIds) {
            pinnedIds.add(id);
        }
        if (this._savePoint) {
            for (const id of this._savePoint._currentIds) {
                pinnedIds.add(id);
            }
        }
        for (const [, id] of this._commands) {
            if (id) {
                pinnedIds.add(id);
            }
        }
        return pinnedIds;
    }

    _discard() {
        for (const id of Object.keys(this._cache)) {
            this._cache[id]._discard();
        }
        if (this._savePoint) {
            const savePoint = this._savePoint;
            this._savePoint = undefined;
            this._restore(savePoint);
            return;
        }
        this._commands = [];
        this._currentIds = [...this.resIds];
        this._unknownRecordCommands = {};
        this._loadingStubIds.clear();
        const limit = this.limit - this._tmpIncreaseLimit;
        this._tmpIncreaseLimit = 0;
        this.model._patchConfig(this.config, { limit });
        this._materializeWindow();
        this.stageCommands(this._initialCommands);
        if (this._commandsPromise) {
            this._commandsPromise.then(() => this._pruneCache());
        } else {
            this._pruneCache();
        }
    }

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
                x2ManyCommands.update(listId(record), {
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
        // Both `_load` and its `sort` caller silently drop ids the server no
        // longer returns -- `_loadRecords` throws only on a ZERO-row response.
        // `count` is the x2many pager total and is derived from `_currentIds`,
        // so a concurrently-unlinked row leaves the pager the moment it leaves
        // the id list; nothing has to reconcile the two.
        this._currentIds = nextCurrentIds;
        this.model._patchConfig(this.config, { limit, offset, orderBy });
    }

    /**
     * @param {number[]} ids
     * @param {{ reload?: boolean }} [options]
     */
    async _replaceWith(ids, { reload = false } = {}) {
        const resIds = reload ? ids : ids.filter((id) => !this._cache[id]);
        if (resIds.length) {
            const records = await this.model._loadRecords(
                { ...this.config, resIds, context: this.context },
                this.evalContext,
            );
            for (const record of records) {
                this._createRecordDatapoint(record);
            }
        }
        const presentIds = ids.filter((id) => this._cache[id]);
        /** @type {Set<DatapointId>} */
        const idSet = new Set(presentIds);
        const updateCommandsToKeep = this._commands.filter(
            (c) => c[0] === x2ManyCommands.UPDATE && idSet.has(c[1]),
        );
        this._commands = [x2ManyCommands.set(presentIds), ...updateCommandsToKeep];
        this._currentIds = [...presentIds];
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
        if (this.offset) {
            this.model._patchConfig(this.config, { offset: 0 });
        }
        this._materializeWindow();
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
