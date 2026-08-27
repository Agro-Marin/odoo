// @ts-check
/** @odoo-module native */

import { markRaw } from "@odoo/owl";
import { reportUncaught } from "@web/core/errors/error_utils";
import { isX2Many } from "@web/core/field_types";
import { x2ManyCommands } from "@web/core/network/commands";
import { deepEqual, omit } from "@web/core/utils/collections/objects";

import { serializeCommands } from "./command_builder.js";
import { EditableListDataPoint } from "./editable_list_datapoint.js";
import { getId, getSpecEvalContext } from "./field_context.js";
import {
    cloneActiveFields,
    completeActiveFields,
    patchActiveFields,
} from "./field_metadata.js";
import { fromUnityToServerValues, invalidateAggregateSpecs } from "./field_values.js";
import { ListMembership } from "./list_membership.js";
import { applyCommands } from "./static_list_command_engine.js";
import { resequenceStaticList, sortBy, sortStaticList } from "./static_list_sort.js";
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

/** @param {Map<DatapointId, [number, any, any?][]>} byId */
function cloneCommandsById(byId) {
    return new Map([...byId].map(([id, cmds]) => [id, cloneCommands(cmds)]));
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

export class StaticList extends EditableListDataPoint {
    static type = "StaticList";

    /**
     * @param {any} _config
     * @param {any} data
     * @param {any} [options]
     */
    setup(_config, data, options = {}) {
        this._parent = options.parent;
        this._onUpdate = options.onUpdate;

        /** @type {Map<DatapointId, RelationalRecord>} */
        this._cache = markRaw(new Map());
        this._commands = [];
        this._initialCommands = [];
        /**
         * @type {Promise<void> | null}
         */
        this._commandsPromise = null;
        this._savePoint = undefined;
        /** @type {Map<DatapointId, [number, any, any?][]>} */
        this._unknownRecordCommands = new Map();
        this._loadingStubIds = new Set();
        /**
         * @type {boolean}
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
        this.handleField = this._findHandleField();
    }

    /** @type {RelationalRecord[]} */
    get records() {
        return this._membership.records;
    }

    set records(records) {
        this._membership.records = records;
    }

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

    /**
     * @returns {import("./record").RelationalRecord[]}
     */
    get selection() {
        return [];
    }

    /**
     * @returns {Promise<void> | null}
     */
    get pendingCommands() {
        return this._commandsPromise;
    }

    /** @returns {RelationalRecord[]} */
    get cachedRecords() {
        return [...this._cache.values()];
    }

    /** @returns {boolean} */
    get hasStagedCommands() {
        return this._commands.length > 0;
    }

    /**
     * @returns {{ add: RelationalRecord[], remove: RelationalRecord[] }}
     */
    get stagedMembershipDelta() {
        const byOpcode = (/** @type {number} */ opcode) =>
            this._commands
                .filter((command) => command[0] === opcode)
                .map((command) => this.getCachedRecord(command[1]))
                .filter(Boolean);
        return {
            add: byOpcode(x2ManyCommands.LINK),
            remove: byOpcode(x2ManyCommands.UNLINK),
        };
    }

    /**
     * @param {DatapointId} id
     * @returns {RelationalRecord | undefined}
     */
    getCachedRecord(id) {
        return this._cache.get(id);
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
                await sortStaticList(this);
            }
            await this._onUpdate();
        });
    }

    /**
     * @returns {boolean}
     */
    canResequence() {
        return Boolean(
            this.handleField &&
            this.orderBy.length &&
            this.orderBy[0].name === this.handleField,
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
        const release = this.beginEditHandover(record);
        try {
            const canProceed = await this.leaveEditMode();
            if (canProceed) {
                await record.switchMode("edit");
            }
            return canProceed;
        } finally {
            release();
        }
    }

    /**
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
                        for (const subRecord of list._cache.values()) {
                            this.model._patchConfig(subRecord.config, patch);
                        }
                        this.model._patchConfig(list.config, patch);
                    }
                }
                record._applyValues(data);
                const ledgerId = listId(record);
                const commands = this._unknownRecordCommands.get(ledgerId);
                this._unknownRecordCommands.delete(ledgerId);
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
        return this.model.mutex.exec(() =>
            resequenceStaticList(this, movedId, targetId),
        );
    }

    /**
     * @param {RelationalRecord} record
     */
    validateExtendedRecord(record) {
        return this.model.mutex.exec(async () => {
            if (!this._currentIds.includes(listId(record))) {
                await this._addRecord(record);
            } else if (!record.hasPendingChanges) {
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
            await this._applyCommands([[x2ManyCommands.CREATE, virtualId]], {
                position,
            });
        } else {
            const currentIds = [...this._currentIds, listId(record)];
            if (this.orderBy.length && sort) {
                await sortStaticList(this, currentIds);
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
        await resequenceStaticList(
            this,
            newRecord.id,
            targetRecord ? targetRecord.id : null,
        );
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
        for (const record of this._cache.values()) {
            record._addSavePoint();
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
        const cachedRecord = this._cache.get(id);
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
        this._cache.set(id, record);
        if (!params.dontApplyCommands) {
            const commands = this._unknownRecordCommands.get(id);
            if (commands) {
                this._unknownRecordCommands.delete(id);
                this.stageCommands(commands);
            }
        }
        return record;
    }

    _clearCommands() {
        this._commands = [];
        this._unknownRecordCommands.clear();
        this._loadingStubIds.clear();
        this._pruneCache();
    }

    /**
     * @param {any[]} commands
     * @returns {void}
     */
    _commitCommands(commands) {
        this._commands = commands;
    }

    /**
     * @param {(string|number)[]} ids
     * @returns {void}
     */
    _commitCurrentIds(ids) {
        this._currentIds = ids;
    }

    /**
     * @param {number} index
     * @param {string|number} id
     * @returns {void}
     */
    _insertMemberAt(index, id) {
        /** @type {ListMembership} */ (this._membership).insertAt(index, id);
    }

    /**
     * @param {string|number} id
     * @returns {void}
     */
    _appendMember(id) {
        /** @type {ListMembership} */ (this._membership).append(id);
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
        this._unknownRecordCommands.clear();
        this._loadingStubIds.clear();
        this._tmpIncreaseLimit = 0;
        this._savePoint = undefined;
        this._materializeWindow();
        this._pruneCache();
        this._replayFailed = false;
        this._healMissingWindow();
    }

    healFailedReplay() {
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
        const record = this._cache.get(virtualId);
        if (!record) {
            return;
        }
        this._cache.delete(virtualId);
        record.assignResId(resId);
        this._cache.set(resId, record);
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
        for (const [id, record] of this._cache) {
            if (!pinnedIds.has(id)) {
                this._extendedRecords.delete(record.id);
                this._cache.delete(id);
            }
        }
        this._pruneExtendedRecords();
    }

    /**
     * @returns {void}
     */
    _pruneExtendedRecords() {
        if (!this._extendedRecords.size) {
            return;
        }
        const live = new Set();
        for (const record of this._cache.values()) {
            live.add(record.id);
        }
        for (const datapointId of this._extendedRecords) {
            if (!live.has(datapointId)) {
                this._extendedRecords.delete(datapointId);
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
        for (const record of this._cache.values()) {
            record._discard();
        }
        if (this._savePoint) {
            const savePoint = this._savePoint;
            this._savePoint = undefined;
            this._restore(savePoint);
            return;
        }
        this._commands = [];
        this._currentIds = [...this.resIds];
        this._unknownRecordCommands.clear();
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

        await sortStaticList(this);
    }

    /** @param {{ withReadonly?: boolean }} [options] */
    _getCommands({ withReadonly } = {}) {
        return serializeCommands(this._commands, {
            unknownRecordCommands: this._unknownRecordCommands,
            fields: this.fields,
            activeFields: this.activeFields,
            context: this.context,
            withReadonly,
            getRecord: (id) => this._cache.get(id),
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
            const record = this._cache.get(resId);
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
        const window = currentIds.map((id) => this._cache.get(id));
        if (window.includes(undefined)) {
            const missing = new Set(currentIds.filter((id) => !this._cache.has(id)));
            nextCurrentIds = nextCurrentIds.filter((id) => !missing.has(id));
        }
        this.records = /** @type {RelationalRecord[]} */ (window.filter(Boolean));
        this._currentIds = nextCurrentIds;
        this.model._patchConfig(this.config, { limit, offset, orderBy });
    }

    /**
     * @param {number[]} ids
     */
    async _replaceWith(ids) {
        const resIds = ids.filter((id) => !this._cache.has(id));
        if (resIds.length) {
            const records = await this.model._loadRecords(
                { ...this.config, resIds, context: this.context },
                this.evalContext,
            );
            for (const record of records) {
                this._createRecordDatapoint(record);
            }
        }
        const presentIds = ids.filter((id) => this._cache.has(id));
        /** @type {Set<DatapointId>} */
        const idSet = new Set(presentIds);
        const updateCommandsToKeep = this._commands.filter(
            (c) => c[0] === x2ManyCommands.UPDATE && idSet.has(c[1]),
        );
        this._commands = [x2ManyCommands.set(presentIds), ...updateCommandsToKeep];
        this._currentIds = [...presentIds];
        for (const id of [...this._unknownRecordCommands.keys()]) {
            if (!idSet.has(id)) {
                this._unknownRecordCommands.delete(id);
            }
        }
        for (const id of [...this._loadingStubIds]) {
            if (!idSet.has(id)) {
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
        for (const record of this._cache.values()) {
            record._setEvalContext();
        }
    }
}
