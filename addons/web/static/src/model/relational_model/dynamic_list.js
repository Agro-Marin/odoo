// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/dynamic_list */

import { markRaw } from "@odoo/owl";
import { x2ManyCommands } from "@web/core/network/commands";
import { _t } from "@web/core/translation";
import { unique } from "@web/core/utils/collections/arrays";
import { Operation } from "@web/core/utils/operation";

import { buildKnownValuesKwargs } from "./concurrency_baseline.js";
import { DataPoint } from "./datapoint.js";
import { getSpecEvalContext, isX2Many } from "./field_context.js";
import { getFieldsSpec } from "./field_spec.js";
import { RelationalRecord } from "./record.js";
import { resequence } from "./resequence.js";
import { computeNextOrderBy } from "./static_list_utils.js";

const DEFAULT_HANDLE_FIELD = "sequence";

/**
 * @abstract
 */
export class DynamicList extends DataPoint {
    /**
     * @type {DataPoint["setup"]}
     */
    setup(...args) {
        super.setup(...args);
        /** @type {number} */
        this.count = 0;
        this.handleField = Object.keys(this.activeFields).find(
            (fieldName) => this.activeFields[fieldName].isHandle,
        );
        if (!this.handleField && DEFAULT_HANDLE_FIELD in this.fields) {
            this.handleField = DEFAULT_HANDLE_FIELD;
        }
        this.isDomainSelected = false;
        /**
         * Holder for the record `enterEditMode` is on its way to. `markRaw` is
         * load-bearing: this is bookkeeping for a handover, not state anyone
         * should re-render on. Stored plainly on the reactive it would notify
         * `isEditing`'s subscribers twice per handover -- once on claim, once
         * on release -- which is one render MORE than the round-trip this
         * exists to remove.
         *
         * @type {{ record: import("./record").RelationalRecord | null }}
         */
        this._editHandover = markRaw({ record: null });
    }

    /**
     * Same shape as `StaticList#evalContext` and `RelationalRecord#evalContext`:
     * a modifier written against `uid` or `allowed_company_ids` must evaluate
     * the same way in a top-level list as it does inside an x2many.
     *
     * @returns {Record<string, any>}
     */
    get evalContext() {
        return getSpecEvalContext(this.config);
    }

    /**
     * Empties the list in place when a sample-data view is replaced by the real,
     * empty result. Each subclass clears the storage it owns, so a caller never
     * has to ask which kind of list it is holding.
     *
     * @abstract
     * @returns {void}
     */
    clearSampleData() {
        this._abstract("clearSampleData");
    }

    /**
     * @param {string} name
     * @returns {never}
     */
    _abstract(name) {
        throw new Error(
            `${this.constructor.name} must implement DynamicList#${name}()`,
        );
    }

    /**
     * @abstract
     * @param {number} _offset
     * @param {number} _limit
     * @param {import("@web/core/utils/order_by").OrderTerm[]} _orderBy
     * @param {import("@web/core/domain").DomainListRepr} _domain
     * @returns {Promise<any>}
     */
    async _load(_offset, _limit, _orderBy, _domain) {
        this._abstract("_load");
    }

    /**
     * @abstract
     * @param {(string | number)[]} _recordIds
     */
    _removeRecords(_recordIds) {
        this._abstract("_removeRecords");
    }

    /**
     * @abstract
     * @param {DataPoint} _dp
     * @returns {number}
     */
    _getDPresId(_dp) {
        return this._abstract("_getDPresId");
    }

    /**
     * @abstract
     * @param {DataPoint} _dp
     * @param {string} _handleField
     * @returns {any}
     */
    _getDPFieldValue(_dp, _handleField) {
        this._abstract("_getDPFieldValue");
    }

    /**
     * @abstract
     * @returns {RelationalRecord[]}
     */
    get records() {
        return [];
    }

    get groupBy() {
        return [];
    }

    get orderBy() {
        return this.config.orderBy;
    }

    get domain() {
        return this.config.domain;
    }

    get editedRecord() {
        return this.records.find((record) => record.isInEdition);
    }

    /**
     * Whether the list is in inline edition, INCLUDING the gap in
     * `enterEditMode` where the outgoing record has already left edition and
     * the incoming one has not entered it yet.
     *
     * `editedRecord` is momentarily null across that gap, so anything derived
     * from it flips off and back on within a single interaction. For a
     * per-record consumer that is harmless; for a LIST-WIDE one it is not,
     * because every row subscribes to the derived value and a round-trip
     * re-renders all of them twice for a state that is never painted. Moving
     * the edited row of a 40-row list cost 81 row renders instead of 3.
     *
     * Use this for "is the user editing this list" questions. Use
     * `editedRecord` when you need the record itself.
     *
     * @returns {boolean}
     */
    get isEditing() {
        return Boolean(this._editHandover.record || this.editedRecord);
    }

    /**
     * Declare that edition is moving to `record`, for a caller that leaves and
     * enters as two separate steps instead of letting `enterEditMode` do both.
     *
     * `enterEditMode` claims the handover itself, so anything routed through it
     * needs nothing here. `ListRenderer#editNextRecord` (the Enter key) cannot
     * use it — it needs `leaveEditMode({ validate: true })`, a stricter leave
     * than `enterEditMode` performs — so it drives the two halves itself, and
     * without a claim `isEditing` drops to false between them. That cost 61 row
     * renders on a 30-row list where Tab, which does route through
     * `enterEditMode`, cost 4.
     *
     * @param {import("./record").RelationalRecord} record
     * @returns {() => void} release, safe to call more than once
     */
    beginEditHandover(record) {
        this._editHandover.record = record;
        return () => {
            this._editHandover.record = null;
        };
    }

    get isRecordCountTrustable() {
        return true;
    }

    /**
     * @returns {number}
     */
    get recordCount() {
        return this.count;
    }

    get limit() {
        return this.config.limit;
    }

    get offset() {
        return this.config.offset;
    }

    get selection() {
        return this.records.filter((record) => record.selected);
    }

    archive(isSelected) {
        return this.model.mutex.exec(() => this._toggleArchive(isSelected, true));
    }

    canResequence() {
        return !!this.handleField;
    }

    deleteRecords(records = []) {
        return this.model.mutex.exec(() => this._deleteRecords(records));
    }

    duplicateRecords(records = []) {
        return this.model.mutex.exec(() => this._duplicateRecords(records));
    }

    async enterEditMode(record) {
        if (this.editedRecord === record) {
            return true;
        }
        // Claimed BEFORE awaiting the outgoing record out of edition, so
        // `isEditing` stays continuously true across the handover instead of
        // reporting a transient "nothing is being edited" that no frame ever
        // shows. Cleared in `finally` so an aborted handover (leaveEditMode
        // refusing, or the tail throwing) cannot strand the list as editing.
        this._editHandover.record = record;
        try {
            const canProceed = await this.leaveEditMode();
            if (canProceed) {
                const tail = () => {
                    record._checkValidity();
                    this.model._patchConfig(record.config, { mode: "edit" });
                };
                if (this.model.urgentSave.isActive) {
                    tail();
                } else {
                    await this.model.mutex.exec(tail);
                }
            }
            return canProceed;
        } finally {
            this._editHandover.record = null;
        }
    }

    /**
     * @param {boolean} [isSelected]
     * @returns {Promise<number[]>}
     */
    async getResIds(isSelected) {
        let resIds;
        if (isSelected) {
            if (this.isDomainSelected) {
                resIds = await this.model.orm.search(this.resModel, this.domain, {
                    limit: this.model.activeIdsLimit,
                    context: this.context,
                });
            } else {
                resIds = this.selection.map((r) => r.resId);
            }
        } else {
            resIds = this.records.map((r) => r.resId);
        }
        return unique(resIds);
    }

    /**
     * Mass edit stages x2many changes on the edited record only. Replay its
     * commands onto every OTHER selected record so they all carry the same
     * relation before validity is judged and the values are read back.
     *
     * `display_name` is re-attached to LINK commands when the list tracks it:
     * the other records' lists have never fetched those rows, so without it the
     * tag renders blank until the next read.
     *
     * @param {RelationalRecord} editedRecord
     * @param {Record<string, any>} changes
     * @param {RelationalRecord[]} selectedRecords
     * @returns {Promise<void>}
     */
    async _applyMultiEditX2ManyCommands(editedRecord, changes, selectedRecords) {
        const proms = [];
        for (const fieldName of Object.keys(changes)) {
            if (isX2Many(this.fields[fieldName])) {
                const list = editedRecord.data[fieldName];
                let commands = list._getCommands();
                if ("display_name" in list.activeFields) {
                    commands = commands.map((command) => {
                        if (command[0] === x2ManyCommands.LINK) {
                            const relRecord = list.getCachedRecord(command[1]);
                            return [
                                command[0],
                                command[1],
                                { display_name: relRecord.data.display_name },
                            ];
                        }
                        return command;
                    });
                }
                for (const record of selectedRecords) {
                    if (record !== editedRecord) {
                        proms.push(record.data[fieldName]._applyCommands(commands));
                    }
                }
            }
        }
        await Promise.all(proms);
    }

    /**
     * Split the selection into the records this save may write and those it may
     * not. A record is excluded when any changed field is readonly ON THAT
     * RECORD, or when it fails validation.
     *
     * Only the edited record reports its invalid fields; the rest validate
     * `silent` because the user is looking at one row and would otherwise get a
     * notification per selected record.
     *
     * @param {RelationalRecord[]} selectedRecords
     * @param {RelationalRecord} editedRecord
     * @param {Record<string, any>} changes
     * @returns {{ validRecords: RelationalRecord[], invalidRecords: RelationalRecord[] }}
     */
    _partitionByValidity(selectedRecords, editedRecord, changes) {
        const validRecords = [];
        const invalidRecords = [];
        for (const record of selectedRecords) {
            const isEditedRecord = record === editedRecord;
            if (
                Object.keys(changes).every(
                    (fieldName) => !record._isReadonly(fieldName),
                ) &&
                record._checkValidity({ silent: !isEditedRecord })
            ) {
                validRecords.push(record);
            } else {
                invalidRecords.push(record);
            }
        }
        return { validRecords, invalidRecords };
    }

    /**
     * The write to send, as a thunk so the caller can run it inside its own
     * try/catch after the confirmation hook.
     *
     * Two shapes, and the choice is not cosmetic: an `Operation` value (an
     * increment, say) resolves to a DIFFERENT number per record, so those go
     * through `web_save_multi` with one vals dict each. Everything else writes
     * one identical vals dict to every id via `web_save`.
     *
     * @param {RelationalRecord} editedRecord
     * @param {RelationalRecord[]} validRecords
     * @param {Record<string, any>} changes
     * @returns {() => Promise<any>}
     */
    _buildMultiSaveCall(editedRecord, validRecords, changes) {
        const resIds = unique(validRecords.map((r) => r.resId));
        const kwargs = {
            context: this.context,
            specification: getFieldsSpec(
                editedRecord.activeFields,
                editedRecord.fields,
                getSpecEvalContext(editedRecord.config),
            ),
        };
        let save;
        if (Object.values(changes).some((v) => v instanceof Operation)) {
            const changesById = {};
            for (const record of validRecords) {
                changesById[record.resId] =
                    changesById[record.resId] || record._getChanges();
            }
            const valsList = resIds.map((resId) => changesById[resId]);
            const multiKwargs = buildKnownValuesKwargs(
                validRecords,
                Object.keys(changes),
                kwargs,
            );
            save = () =>
                this.model.orm.webSaveMulti(
                    this.resModel,
                    resIds,
                    valsList,
                    multiKwargs,
                );
        } else {
            const vals = editedRecord._getChanges();
            const saveKwargs = buildKnownValuesKwargs(
                validRecords,
                Object.keys(vals),
                kwargs,
            );
            save = () =>
                this.model.orm.webSave(this.resModel, resIds, vals, saveKwargs);
        }
        return save;
    }

    /**
     * Write the server's read-back onto the records that were saved.
     *
     * Keyed by id and skipped when absent rather than zipped positionally: the
     * server returns a row per WRITTEN record, and `resIds` was uniqued, so the
     * two lists need not line up when the same record is selected twice.
     *
     * @param {any[]} records rows returned by web_save / web_save_multi
     * @param {RelationalRecord[]} validRecords
     * @returns {void}
     */
    _applyMultiSaveResult(records, validRecords) {
        const serverValuesById = Object.fromEntries(
            records.map((record) => [record.id, record]),
        );
        for (const record of validRecords) {
            const serverValues = serverValuesById[/** @type {number} */ (record.resId)];
            if (!serverValues) {
                continue;
            }
            record._setData(serverValues);
            this.model._updateSimilarRecords(record, serverValues);
        }
    }

    /** @param {{ discard?: boolean }} [options] */
    async leaveEditMode({ discard } = {}) {
        if (this.model.urgentSave.isActive) {
            return this._leaveEditMode({ discard });
        }
        const editedRecord = this.editedRecord;
        if (discard) {
            this._recordToDiscard = editedRecord;
        }
        try {
            if (editedRecord) {
                await this.model._askChanges();
            }
            if (!discard && this.editedRecord) {
                await this.model._askChanges();
            }
            return await this.model.mutex.exec(() => this._leaveEditMode({ discard }));
        } finally {
            if (discard) {
                this._recordToDiscard = null;
            }
        }
    }

    load(params = {}) {
        const limit = params.limit === undefined ? this.limit : params.limit;
        const offset = params.offset === undefined ? this.offset : params.offset;
        const orderBy = params.orderBy === undefined ? this.orderBy : params.orderBy;
        const domain = params.domain === undefined ? this.domain : params.domain;
        return this.model.mutex.exec(() => this._load(offset, limit, orderBy, domain));
    }

    async multiSave(record, changes) {
        return this.model.mutex.exec(() => this._multiSave(record, changes));
    }

    selectDomain(value) {
        return this.model.mutex.exec(() => this._selectDomain(value));
    }

    sortBy(fieldName) {
        return this.model.mutex.exec(() => {
            const orderBy = computeNextOrderBy(fieldName, this.orderBy, false, {
                resetOrderBy: [],
            });
            return this._load(this.offset, this.limit, orderBy, this.domain);
        });
    }

    toggleSelection() {
        return this.model.mutex.exec(() => this._toggleSelection());
    }

    unarchive(isSelected) {
        return this.model.mutex.exec(() => this._toggleArchive(isSelected, false));
    }

    /** @returns {Promise<any>} */
    toggleArchiveWithConfirmation(archive, dialogProps = {}) {
        const isSelected = this.isDomainSelected || this.selection.length;
        if (archive) {
            return Promise.resolve(
                this.model.hooks.ui.onConfirmArchive(
                    () => this.archive(isSelected),
                    dialogProps,
                ),
            );
        }
        return this.unarchive(isSelected);
    }

    async _duplicateRecords(records) {
        let resIds;
        if (records.length) {
            resIds = unique(records.map((r) => r.resId));
        } else {
            resIds = await this.getResIds(true);
        }

        const copy = async (resIds) => {
            const copiedRecords = await this.model.orm.call(
                this.resModel,
                "copy",
                [resIds],
                {
                    context: this.context,
                },
            );

            if (resIds.length > copiedRecords.length) {
                this.model.hooks.ui.onDisplayLimitNotification(
                    _t("Some records could not be duplicated"),
                );
            }
            return this.model.load();
        };

        await this.model.hooks.ui.onConfirmDuplicate(resIds, copy);
    }

    async _deleteRecords(records) {
        let resIds;
        if (records.length) {
            resIds = unique(records.map((r) => r.resId));
        } else {
            resIds = await this.getResIds(true);
        }
        const unlinked = await this.model.orm.unlink(this.resModel, resIds, {
            context: this.context,
        });
        if (!unlinked) {
            return false;
        }
        if (
            this.isDomainSelected &&
            resIds.length === this.model.activeIdsLimit &&
            resIds.length < this.recordCount
        ) {
            const msg = _t(
                "Only the first %(count)s records have been deleted (out of %(total)s selected)",
                { count: resIds.length, total: this.recordCount },
            );
            this.model.hooks.ui.onDisplayLimitNotification(msg);
        }
        await this.model.load();
        return unlinked;
    }

    /**
     * @param {{ discard?: boolean }} [options]
     * @returns {Promise<boolean>}
     */
    async _leaveEditMode({ discard } = {}) {
        let editedRecord = this.editedRecord;
        if (!editedRecord) {
            return true;
        }
        let canProceed = true;
        if (discard) {
            this.model.closeUrgentSaveNotification();
            this._recordToDiscard = editedRecord;
            try {
                editedRecord._discard();
            } finally {
                this._recordToDiscard = null;
            }
            editedRecord = this.editedRecord;
            if (editedRecord?.isNew) {
                this._removeRecords([editedRecord.id]);
            }
        } else {
            let isValid = true;
            if (!this.model.urgentSave.isActive) {
                isValid = editedRecord._checkValidity();
            }
            if (editedRecord.isNew && !editedRecord.dirty) {
                this._removeRecords([editedRecord.id]);
            } else if (isValid || editedRecord.dirty) {
                canProceed = await editedRecord._save();
            }
        }

        editedRecord = this.editedRecord;
        if (canProceed && editedRecord) {
            this.model._patchConfig(editedRecord.config, {
                mode: "readonly",
            });
        }
        return canProceed;
    }

    async _leaveSampleMode() {
        if (this.model.useSampleModel) {
            await this._load(this.offset, this.limit, this.orderBy, this.domain);
            this.model.useSampleModel = false;
        }
    }

    async _multiSave(editedRecord, changes) {
        if (!Object.keys(changes).length || editedRecord === this._recordToDiscard) {
            return;
        }
        let canProceed = await this.model.hooks.lifecycle.onWillSaveMulti(
            editedRecord,
            changes,
        );
        if (canProceed === false) {
            return false;
        }

        const selectedRecords = this.selection;

        await this._applyMultiEditX2ManyCommands(
            editedRecord,
            changes,
            selectedRecords,
        );

        selectedRecords.forEach((record) => {
            const _changes = { ...changes };
            for (const fieldName of Object.keys(_changes)) {
                if (isX2Many(this.fields[fieldName])) {
                    _changes[fieldName] = record.data[fieldName];
                }
            }
            record._applyChanges(_changes);
        });

        const { validRecords, invalidRecords } = this._partitionByValidity(
            selectedRecords,
            editedRecord,
            changes,
        );
        const discardInvalidRecords = () =>
            invalidRecords.forEach((record) => record._discard());

        if (!validRecords.length) {
            editedRecord._displayInvalidFieldNotification();
            discardInvalidRecords();
            return false;
        }

        const save = this._buildMultiSaveCall(editedRecord, validRecords, changes);

        const _changes = { ...changes };
        for (const fieldName of Object.keys(changes)) {
            if (this.fields[fieldName].type === "many2many") {
                _changes[fieldName] = changes[fieldName].stagedMembershipDelta;
            }
        }
        discardInvalidRecords();

        canProceed = await this.model.hooks.lifecycle.onAskMultiSaveConfirmation(
            _changes,
            validRecords,
        );
        if (canProceed === false) {
            selectedRecords.forEach((record) => record._discard());
            this.leaveEditMode({ discard: true }).catch((e) => console.error(e));
            return false;
        }

        let records;
        try {
            records = await save();
        } catch (e) {
            selectedRecords.forEach((record) => record._discard());
            this.model._patchConfig(editedRecord.config, { mode: "readonly" });
            throw e;
        }
        this._applyMultiSaveResult(records, validRecords);
        this.model._patchConfig(editedRecord.config, { mode: "readonly" });
        this.model.hooks.lifecycle.onSavedMulti(validRecords);
        return true;
    }

    async _resequence(originalList, resModel, movedId, targetId) {
        if (this.resModel === resModel && !this.canResequence()) {
            return;
        }
        const handleField =
            this.resModel === resModel ? this.handleField : DEFAULT_HANDLE_FIELD;
        const order = this.orderBy.find((o) => o.name === handleField);
        const getSequence = (dp) => dp && this._getDPFieldValue(dp, handleField);
        const getResId = (dp) => this._getDPresId(dp);
        const resequencedRecords = await resequence({
            records: originalList,
            resModel,
            movedId,
            targetId,
            fieldName: handleField,
            asc: order?.asc,
            context: this.context,
            orm: this.model.orm,
            getSequence,
            getResId,
        });
        for (const dpData of resequencedRecords) {
            const dp = originalList.find((d) => getResId(d) === dpData.id);
            if (dp instanceof RelationalRecord) {
                dp._applyValues(dpData);
            } else {
                dp[handleField] = dpData[handleField];
            }
        }
    }

    /**
     * @param {RelationalRecord} record
     * @returns {boolean}
     */
    _isRecordToDiscard(record) {
        return this._recordToDiscard === record;
    }

    _onRecordDeselected() {
        if (this.isDomainSelected) {
            this._selectDomain(false);
        }
    }

    _selectDomain(value) {
        this.isDomainSelected = value;
    }

    async _toggleArchive(isSelected, state) {
        const method = state ? "action_archive" : "action_unarchive";
        const context = this.context;
        const resIds = await this.getResIds(isSelected);
        const action = await this.model.orm.call(this.resModel, method, [resIds], {
            context,
        });
        if (
            this.isDomainSelected &&
            resIds.length === this.model.activeIdsLimit &&
            resIds.length < this.recordCount
        ) {
            const msg = _t(
                "Of the %(selectedRecords)s selected records, only the first %(firstRecords)s have been archived/unarchived.",
                {
                    selectedRecords: this.recordCount,
                    firstRecords: resIds.length,
                },
            );
            this.model.hooks.ui.onDisplayLimitNotification(msg);
        }
        const reload = () => this.model.load();
        return this.model.hooks.ui.onDisplayArchiveAction(action, reload);
    }

    async _toggleSelection() {
        const records = this.records;
        if (records.every((record) => record.selected)) {
            records.forEach((record) => {
                record._toggleSelection(false);
            });
            this._selectDomain(false);
        } else {
            records.forEach((record) => {
                record._toggleSelection(true);
            });
        }
    }
}
