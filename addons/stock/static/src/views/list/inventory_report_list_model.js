/** @odoo-module native */
import { _t } from "@web/core/translation";
import { DynamicRecordList, RelationalModel } from "@web/model/relational_model";

export class InventoryReportListModel extends RelationalModel {
    setup() {
        this._lastCreatedRecordId = null;
        return super.setup(...arguments);
    }

    async _updateSimilarRecords(reloadedRecord, serverValues) {
        if (this.config.isMonoRecord) {
            return;
        }

        const justCreated = reloadedRecord.id === this._lastCreatedRecordId;
        if (justCreated) {
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
    async addNewRecord() {
        const record = await super.addNewRecord(...arguments);
        record.model._lastCreatedRecordId = record.id;
        return record;
    }
}

InventoryReportListModel.DynamicRecordList = InventoryReportListDynamicRecordList;
