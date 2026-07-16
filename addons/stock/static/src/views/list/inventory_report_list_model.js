/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";
import { RelationalModel } from "@web/model/relational_model/relational_model";

export class InventoryReportListModel extends RelationalModel {
    /**
     * Override
     */
    setup() {
        // Id of the datapoint created by the most recent addNewRecord, consumed
        // once by the immediately-following post-create reload (see
        // _updateSimilarRecords). null when no create is pending inspection.
        this._lastCreatedRecordId = null;
        return super.setup(...arguments);
    }

    /**
     * Called after a record is (re)loaded post-save. Detects when the user added a
     * quant that already exists (see stock.quant.create) so we can warn them it was
     * updated instead: its id matches '_lastCreatedRecordId', and create_date equals
     * write_date only for a freshly created record.
     */
    async _updateSimilarRecords(reloadedRecord, serverValues) {
        if (this.config.isMonoRecord) {
            return;
        }

        const justCreated = reloadedRecord.id === this._lastCreatedRecordId;
        if (justCreated) {
            // One-shot: only the reload immediately following the create consumes
            // the token. Clearing it *only on match* (not on every reload) keeps an
            // unrelated interleaved reload from swallowing the token before the real
            // create-reload arrives; and prevents a later legitimate edit of the
            // same datapoint (id unchanged, but write_date > create_date) from
            // re-firing the "already exists" notification.
            this._lastCreatedRecordId = null;
        }
        if (justCreated && serverValues.create_date !== serverValues.write_date) {
            this.env.services.notification.add(
                _t(
                    "You tried to create a record that already exists. The existing record was modified instead.",
                ),
                { title: _t("This record already exists") },
            );
            const duplicateRecords = this.root.records.filter(
                (record) =>
                    record.resId === reloadedRecord.resId &&
                    record.id !== reloadedRecord.id,
            );
            // Drop the added row when it is really an update of an existing record:
            //  - if a duplicate is already loaded (ungrouped, or same group), remove
            //    the added row and apply the server values to the existing one;
            //  - in a grouped list, remove it even when no duplicate is loaded — its
            //    group-by value points at a *different* (folded) group than the one it
            //    was added in, so leaving it there strands a record in the wrong group
            //    and desyncs the grouped renderer's row indexing (spawning spurious
            //    empty edit rows). The real record shows the fresh values when its own
            //    group is opened.
            // In an ungrouped list with no duplicate loaded (the existing record is
            // just off-page/filtered), keep the added row: it correctly shows that
            // existing record, and it is not in any "wrong" group.
            const isGrouped = this.config.groupBy.length > 0;
            if (isGrouped || duplicateRecords.length > 0) {
                await this.root._removeRecords([reloadedRecord.id]);
                for (const record of duplicateRecords) {
                    record._applyValues(serverValues);
                }
            }
        } else {
            super._updateSimilarRecords(...arguments);
        }
    }
}

export class InventoryReportListDynamicRecordList extends DynamicRecordList {
    /**
     * Override
     */
    async addNewRecord() {
        const record = await super.addNewRecord(...arguments);
        // keep created record id on model
        record.model._lastCreatedRecordId = record.id;
        return record;
    }
}

InventoryReportListModel.DynamicRecordList = InventoryReportListDynamicRecordList;
