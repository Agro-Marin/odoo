/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";
import { RelationalModel } from "@web/model/relational_model/relational_model";

export class InventoryReportListModel extends RelationalModel {
    /**
     * Override
     */
    setup(params) {
        // model has not created any record yet
        this._lastCreatedRecordId;
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

        const justCreated = reloadedRecord.id == this._lastCreatedRecordId;
        if (justCreated && serverValues.create_date !== serverValues.write_date) {
            this.env.services.notification.add(
                _t(
                    "You tried to create a record that already exists. The existing record was modified instead."
                ),
                { title: _t("This record already exists") }
            );
            const duplicateRecords = this.root.records.filter(
                (record) => record.resId === reloadedRecord.resId && record.id !== reloadedRecord.id
            );
            if (duplicateRecords.length > 0) {
                /* more than 1 'resId' record loaded in view (user added an already loaded record) :
                 * - both have been updated
                 * - remove the current record (the added one)
                 */
                await this.root._removeRecords([reloadedRecord.id]);
                for (const record of duplicateRecords) {
                    record._applyValues(serverValues);
                }
            }
        } else {
            super._updateSimilarRecords(...arguments)
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
