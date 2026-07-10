// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/dynamic_list - Abstract paginated list with sorting, domain filtering, and drag-and-drop resequencing */

import { _t } from "@web/core/l10n/translation";
import { unique } from "@web/core/utils/collections/arrays";

import { x2ManyCommands } from "./commands.js";
import { DataPoint } from "./datapoint.js";
import { getFieldsSpec } from "./field_spec.js";
import { Operation } from "./operation.js";
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
        // records and count are set by subclasses (DynamicRecordList / DynamicGroupList)
        /** @type {number} */
        this.count = 0;
        this.handleField = Object.keys(this.activeFields).find(
            (fieldName) => this.activeFields[fieldName].isHandle,
        );
        if (!this.handleField && DEFAULT_HANDLE_FIELD in this.fields) {
            this.handleField = DEFAULT_HANDLE_FIELD;
        }
        this.isDomainSelected = false;
        this.evalContext = this.context;
    }

    // -------------------------------------------------------------------------
    // Abstract methods — implemented by DynamicRecordList / DynamicGroupList
    // -------------------------------------------------------------------------

    /**
     * @abstract
     * @param {number} _offset
     * @param {number} _limit
     * @param {import("@web/core/utils/order_by").OrderTerm[]} _orderBy
     * @param {import("@web/core/domain").DomainListRepr} _domain
     * @returns {Promise<any>}
     */
    async _load(_offset, _limit, _orderBy, _domain) {}

    /**
     * @abstract
     * @param {(string | number)[]} _recordIds
     */
    _removeRecords(_recordIds) {}

    /**
     * @abstract
     * @param {DataPoint} _dp
     * @returns {number}
     */
    _getDPresId(_dp) {
        return 0;
    }

    /**
     * @abstract
     * @param {DataPoint} _dp
     * @param {string} _handleField
     * @returns {any}
     */
    _getDPFieldValue(_dp, _handleField) {}

    // -------------------------------------------------------------------------
    // Getters
    // -------------------------------------------------------------------------

    /**
     * List of records. Subclasses must override with their own getter:
     * - DynamicRecordList: backed by `_records` field
     * - DynamicGroupList: computed from groups
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

    /**
     * Be careful that this getter is costly, as it iterates over the whole list
     * of records. This property should not be accessed in a loop.
     */
    get editedRecord() {
        return this.records.find((record) => record.isInEdition);
    }

    get isRecordCountTrustable() {
        return true;
    }

    get limit() {
        return this.config.limit;
    }

    get offset() {
        return this.config.offset;
    }

    /**
     * Be careful that this getter is costly, as it iterates over the whole list
     * of records. This property should not be accessed in a loop.
     */
    get selection() {
        return this.records.filter((record) => record.selected);
    }

    // -------------------------------------------------------------------------
    // Public
    // -------------------------------------------------------------------------

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
        const canProceed = await this.leaveEditMode();
        if (canProceed) {
            record._checkValidity();
            this.model._patchConfig(record.config, { mode: "edit" });
        }
        return canProceed;
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

    /** @param {{ discard?: boolean }} [options] */
    async leaveEditMode({ discard } = {}) {
        let editedRecord = this.editedRecord;
        if (editedRecord) {
            let canProceed = true;
            if (discard) {
                this._recordToDiscard = editedRecord;
                try {
                    await editedRecord.discard();
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
                    isValid = await editedRecord.checkValidity();
                    editedRecord = this.editedRecord;
                    if (!editedRecord) {
                        return true;
                    }
                }
                if (editedRecord.isNew && !editedRecord.dirty) {
                    this._removeRecords([editedRecord.id]);
                } else if (isValid || editedRecord.dirty) {
                    canProceed = await editedRecord.save();
                }
            }

            editedRecord = this.editedRecord;
            if (canProceed && editedRecord) {
                this.model._patchConfig(editedRecord.config, {
                    mode: "readonly",
                });
            } else {
                return canProceed;
            }
        }
        return true;
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
            // Same asc → desc → reset cycling as StaticList.sortBy, except the
            // reset clears the order entirely (next load uses the server /
            // default order) instead of falling back to "id asc".
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

    toggleArchiveWithConfirmation(archive, dialogProps = {}) {
        const isSelected = this.isDomainSelected || this.selection.length;
        if (archive) {
            this.model.hooks.ui.onConfirmArchive(
                isSelected,
                () => this.archive(isSelected),
                () => this.unarchive(isSelected),
                dialogProps,
            );
        } else {
            this.unarchive(isSelected);
        }
    }

    // -------------------------------------------------------------------------
    // Protected
    // -------------------------------------------------------------------------

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
            resIds.length < this.count
        ) {
            const msg = _t(
                "Only the first %(count)s records have been deleted (out of %(total)s selected)",
                { count: resIds.length, total: this.count },
            );
            this.model.hooks.ui.onDisplayLimitNotification(msg);
        }
        await this.model.load();
        return unlinked;
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

        const selectedRecords = this.selection; // costly getter => compute it once

        // special treatment for x2manys: apply commands on all selected record's static lists
        const proms = [];
        for (const fieldName of Object.keys(changes)) {
            if (["one2many", "many2many"].includes(this.fields[fieldName].type)) {
                const list = editedRecord.data[fieldName];
                let commands = list._getCommands();
                if ("display_name" in list.activeFields) {
                    // add display_name to LINK commands to prevent a web_read by selected record.
                    // Pass-through commands (LINK included) are shared by reference with the
                    // edited record's own command log (see serializeCommands), so build fresh
                    // LINK tuples instead of mutating command[2] in place — otherwise we'd
                    // rewrite the edited record's stored commands.
                    commands = commands.map((command) => {
                        if (command[0] === x2ManyCommands.LINK) {
                            const relRecord = list._cache[command[1]];
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
        // apply changes on all selected records (for x2manys, the change is the static list itself)
        selectedRecords.forEach((record) => {
            const _changes = { ...changes };
            for (const fieldName of Object.keys(_changes)) {
                if (["one2many", "many2many"].includes(this.fields[fieldName].type)) {
                    _changes[fieldName] = record.data[fieldName];
                }
            }
            record._applyChanges(_changes);
        });

        // determine valid and invalid records
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
        const discardInvalidRecords = () =>
            invalidRecords.forEach((record) => record._discard());

        if (!validRecords.length) {
            editedRecord._displayInvalidFieldNotification();
            discardInvalidRecords();
            return false;
        }

        // generate the save callback with the values to save (must be done before discarding
        // invalid records, in case the editedRecord is itself invalid)
        const resIds = unique(validRecords.map((r) => r.resId));
        const kwargs = {
            context: this.context,
            specification: getFieldsSpec(
                editedRecord.activeFields,
                editedRecord.fields,
            ),
        };
        let save;
        if (Object.values(changes).some((v) => v instanceof Operation)) {
            // "changes" contains a Field Operation => we must call the web_save_multi method to
            // save each record individually
            const changesById = {};
            for (const record of validRecords) {
                changesById[record.resId] =
                    changesById[record.resId] || record._getChanges();
            }
            const valsList = resIds.map((resId) => changesById[resId]);
            save = () =>
                this.model.orm.webSaveMulti(this.resModel, resIds, valsList, kwargs);
        } else {
            const vals = editedRecord._getChanges();
            save = () => this.model.orm.webSave(this.resModel, resIds, vals, kwargs);
        }

        const _changes = { ...changes };
        for (const fieldName of Object.keys(changes)) {
            if (this.fields[fieldName].type === "many2many") {
                const list = changes[fieldName];
                _changes[fieldName] = {
                    add: list._commands
                        .filter((command) => command[0] === x2ManyCommands.LINK)
                        .map((command) => list._cache[command[1]]),
                    remove: list._commands
                        .filter((command) => command[0] === x2ManyCommands.UNLINK)
                        .map((command) => list._cache[command[1]]),
                };
            }
        }
        discardInvalidRecords();

        // ask confirmation
        canProceed = await this.model.hooks.lifecycle.onAskMultiSaveConfirmation(
            _changes,
            validRecords,
        );
        if (canProceed === false) {
            selectedRecords.forEach((record) => record._discard());
            // Deliberately not awaited: _multiSave runs inside a
            // model.mutex.exec critical section, and leaveEditMode's discard
            // path re-enters the mutex (record.discard), so awaiting here
            // would deadlock. Catch rejections so they don't go unhandled.
            this.leaveEditMode({ discard: true }).catch((e) => console.error(e));
            return false;
        }

        // save changes
        let records;
        try {
            records = await save();
        } catch (e) {
            selectedRecords.forEach((record) => record._discard());
            this.model._patchConfig(editedRecord.config, { mode: "readonly" });
            throw e;
        }
        const serverValuesById = Object.fromEntries(
            records.map((record) => [record.id, record]),
        );
        for (const record of validRecords) {
            const serverValues = serverValuesById[/** @type {number} */ (record.resId)];
            if (!serverValues) {
                // The server returned fewer rows than requested (record
                // concurrently deleted/filtered by the written value):
                // _setData(undefined) would wipe the record's values to {}
                // (same guard as static_list_command_engine's UPDATE path).
                continue;
            }
            record._setData(serverValues);
            this.model._updateSimilarRecords(record, serverValues);
        }
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

    // -------------------------------------------------------------------------
    // Record-facing narrow interface
    //
    // Selection/discard bookkeeping lives in the list; records it owns call
    // these instead of reading/writing the list's protected state directly
    // (``isDomainSelected``/``_selectDomain``/``_recordToDiscard``).
    // -------------------------------------------------------------------------

    /**
     * Whether the given record is the one currently being discarded through
     * ``leaveEditMode({ discard: true })``. Used by the multi-edit validation
     * flow to skip selection side-effects on a deliberate discard.
     *
     * @param {RelationalRecord} record
     * @returns {boolean}
     */
    _isRecordToDiscard(record) {
        return this._recordToDiscard === record;
    }

    /**
     * Called by a record when it is deselected: a partial deselection
     * invalidates the "whole domain selected" state.
     */
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
            resIds.length < this.count
        ) {
            const msg = _t(
                "Of the %(selectedRecords)s selected records, only the first %(firstRecords)s have been archived/unarchived.",
                {
                    selectedRecords: this.count,
                    firstRecords: resIds.length,
                },
            );
            this.model.hooks.ui.onDisplayLimitNotification(msg);
        }
        const reload = () => this.model.load();
        return this.model.hooks.ui.onDisplayArchiveAction(action, reload);
    }

    async _toggleSelection() {
        if (this.selection.length === this.records.length) {
            this.records.forEach((record) => {
                record._toggleSelection(false);
            });
            this._selectDomain(false);
        } else {
            this.records.forEach((record) => {
                record._toggleSelection(true);
            });
        }
    }
}
