// @ts-check

/** @module @web/model/relational_model/static_list - In-memory x2many list: add, remove, reorder records and generate ORM commands */

import { markRaw } from "@odoo/owl";
import { intersection } from "@web/core/utils/collections/arrays";
import { omit } from "@web/core/utils/collections/objects";
import { x2ManyCommands } from "./commands";

import { serializeCommands } from "./command_builder";
import { DataPoint } from "./datapoint";
import { getBasicEvalContext, getId } from "./field_context";
import { completeActiveFields, patchActiveFields } from "./field_metadata";
import { fromUnityToServerValues } from "./field_values";
import { applyCommands } from "./static_list_command_engine";
import { resequence, sort as sortRecords, sortBy } from "./static_list_sort";
import { copyRecordData } from "./static_list_utils";

/** @import { RelationalRecord } from "./record" */

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
        this._savePoint = undefined;
        this._unknownRecordCommands = {}; // tracks update commands on records we haven't fetched yet
        this._currentIds = [...this.resIds];
        this._initialCurrentIds = [...this.currentIds];
        this._needsReordering = false;
        this._tmpIncreaseLimit = 0;
        // In kanban and non editable list views, x2many records can be opened in a form view in
        // dialog, which may contain other fields than the kanban or list view. The next set keeps
        // tracks of records we already opened in dialog and thus for which we already modified the
        // config to add the form view's fields in activeFields.
        this._extendedRecords = new Set();

        /** @type {RelationalRecord[]} */
        this.records = data
            .slice(this.offset, this.limit)
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
     * Adds a new record to an x2many relation. If params.record is given, adds
     * given record (use case: after saving the form dialog in a, e.g., non
     * editable x2many list). Otherwise, do an onchange to get the initial
     * values and create a new Record (e.g. after clicking on Add a line in an
     * editable x2many list).
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
                [x2ManyCommands.DELETE, record.resId || record._virtualId],
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
     * This method is meant to be used in a very specific usecase: when an x2many record is viewed
     * or edited through a form view dialog (e.g. x2many kanban or non editable list). In this case,
     * the form typically contains different fields than the kanban or list, so we need to "extend"
     * the fields and activeFields. If the record opened in a form view dialog already exists, we
     * modify it's config to add the new fields. If it is a new record, we create it with the
     * extended config.
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
            Object.assign(this.fields, params.fields);
            const activeFields = { ...params.activeFields };
            for (const fieldName in this.activeFields) {
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
                };

                // case 1: the record already exists
                if (this._extendedRecords.has(record.id)) {
                    // case 1.1: the record has already been extended
                    // -> simply store a savepoint
                    this.model._updateConfig(record.config, config, {
                        reload: false,
                    });
                    record._addSavePoint();
                    return record;
                }
                // case 1.2: the record is extended for the first time, and it now potentially has
                // more fields than before (or x2many fields displayed differently)
                // -> if it isn't a new record, load it to retrieve the values of new fields
                // -> generate default values for new fields
                // -> recursively update the config of the record and it's sub datapoints
                // -> apply the loaded values in the case of a not new record
                // -> store a savepoint
                // These operations must be done in that specific order to ensure that the model is
                // mutated only once (in a tick), and that datapoints have the correct config to
                // handle field values they receive.
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
                this.model._updateConfig(record.config, config, {
                    reload: false,
                });
                record._applyDefaultValues();
                for (const fieldName in record.activeFields) {
                    if (
                        ["one2many", "many2many"].includes(
                            record.fields[fieldName].type,
                        )
                    ) {
                        const list = record.data[fieldName];
                        const patch = {
                            activeFields: activeFields[fieldName].related.activeFields,
                            fields: activeFields[fieldName].related.fields,
                        };
                        for (const subRecord of Object.values(list._cache)) {
                            this.model._updateConfig(subRecord.config, patch, {
                                reload: false,
                            });
                        }
                        this.model._updateConfig(list.config, patch, {
                            reload: false,
                        });
                    }
                }
                record._applyValues(data);
                const commands = this._unknownRecordCommands[record.resId];
                delete this._unknownRecordCommands[record.resId];
                if (commands) {
                    this._applyCommands(commands);
                }
                record._addSavePoint();
            } else {
                // case 2: the record is a new record
                // -> simply create one with the extended config
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
            await this._applyCommands([[x2ManyCommands.UNLINK, record.resId]]);
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
    load({ limit, offset, orderBy } = {}) {
        return this.model.mutex.exec(async () => {
            const editedRecord = this.editedRecord;
            if (editedRecord && !(await editedRecord.checkValidity())) {
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
                ...(add || []).map((id) => [x2ManyCommands.LINK, id]),
                ...(remove || []).map((id) => [x2ManyCommands.UNLINK, id]),
            ];
            await this._applyCommands(commands, { canAddOverLimit: true });
            await this._onUpdate();
        });
    }

    async resequence(movedId, targetId) {
        return this.model.mutex.exec(() => resequence(this, movedId, targetId));
    }

    /**
     * This method is meant to be called when a record, which has previously been extended to be
     * displayed in a form view dialog (see @extendRecord) is saved. In this case, we may need to
     * add this record to the list (if it is a new one), and to notify the parent record of the
     * update. We may also want to sort the list.
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
                const index = this._currentIds.findIndex((id) => id === virtualId);
                this._currentIds.splice(index, 1);
                this.records.splice(
                    this.records.findIndex((r) => r === record),
                    1,
                );
                this._commands = this._commands.filter((c) => c[1] !== virtualId);
                this.count--;
                if (this._tmpIncreaseLimit > 0) {
                    this.model._updateConfig(
                        this.config,
                        { limit: this.limit - 1 },
                        { reload: false },
                    );
                    this._tmpIncreaseLimit--;
                }
            }
        }
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
            this._commands.unshift(command);
        } else if (position === "bottom") {
            this.records.push(record);
            this._currentIds.splice(this.offset + this.limit, 0, record._virtualId);
            if (this.records.length > this.limit) {
                this._tmpIncreaseLimit++;
                const nextLimit = this.limit + 1;
                this.model._updateConfig(
                    this.config,
                    { limit: nextLimit },
                    { reload: false },
                );
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
            }
            this._currentIds = currentIds;
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
            this._tmpIncreaseLimit++;
            const nextLimit = this.limit + 1;
            this.model._updateConfig(
                this.config,
                { limit: nextLimit },
                { reload: false },
            );
        }
        await this._addRecord(newRecord);
        await resequence(this, newRecord.id, this.records[index].id);
        newRecord.dirty = false;
        return newRecord;
    }

    _addSavePoint() {
        for (const id in this._cache) {
            this._cache[id]._addSavePoint();
        }
        this._savePoint = markRaw({
            _commands: [...this._commands],
            _currentIds: [...this._currentIds],
            count: this.count,
        });
    }

    _applyCommands(commands, options) {
        return applyCommands(this, commands, options);
    }

    _applyInitialCommands(commands) {
        this._applyCommands(commands);
        this._initialCommands = [...commands];
        this._initialCurrentIds = [...this._currentIds];
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
        /** @type {any} */
        const config = {
            context: this.context,
            activeFields: Object.assign({}, params.activeFields || this.activeFields),
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
                this._applyCommands(commands);
            }
        }
        return record;
    }

    _clearCommands() {
        this._commands = [];
        this._unknownRecordCommands = {};
    }

    _discard() {
        for (const id in this._cache) {
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
        this.model._updateConfig(this.config, { limit }, { reload: false });
        this.records = this._currentIds
            .slice(this.offset, this.limit)
            .map((resId) => this._cache[resId]);
        if (!this._savePoint) {
            this._applyCommands(this._initialCommands);
        }
        this._savePoint = undefined;
    }

    /**
     * @fixme: this method is naive and ineffective (it triggers a lot of onchange rpcs)
     */
    async _duplicateRecords(records, options) {
        const targetIndex =
            options.targetIndex ?? this.records.indexOf(records.at(-1)) + 1;
        const copyFields = options.copyFields || [];
        let sequence = this.records[targetIndex - 1].data[this.handleField] + 1;
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
            this._tmpIncreaseLimit += localIncreaseLimit;
            const nextLimit = this.limit + localIncreaseLimit;
            this.model._updateConfig(
                this.config,
                { limit: nextLimit },
                { reload: false },
            );
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
            // record has already been loaded -> check if we already read all orderBy fields
            fieldNames = fieldNames.filter((fieldName) => fieldName !== "id");
            return (
                intersection(fieldNames, record.fieldNames).length !== fieldNames.length
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
        await this.model._updateConfig(
            this.config,
            { limit, offset, orderBy },
            { reload: false },
        );
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
        const updateCommandsToKeep = this._commands.filter(
            (c) => c[0] === x2ManyCommands.UPDATE && ids.includes(c[1]),
        );
        this._commands = [x2ManyCommands.set(ids), ...updateCommandsToKeep];
        this._currentIds = [...ids];
        this.count = this._currentIds.length;
        if (this._currentIds.length > this.limit) {
            this._tmpIncreaseLimit = this._currentIds.length - this.limit;
            const nextLimit = this.limit + this._tmpIncreaseLimit;
            this.model._updateConfig(
                this.config,
                { limit: nextLimit },
                { reload: false },
            );
        }
    }

    _updateContext(context) {
        Object.assign(this.context, context);
        for (const record of Object.values(this._cache)) {
            record._setEvalContext();
        }
    }
}
