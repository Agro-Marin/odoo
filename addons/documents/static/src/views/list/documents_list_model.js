/** @odoo-module native */
import { listView } from "@web/views/list";
import { DocumentsModelMixin } from "../documents_model_mixin.js";
import { DocumentsRecordMixin } from "../documents_record_mixin.js";

const ListModel = listView.Model;
export class DocumentsListModel extends DocumentsModelMixin(ListModel) {
    async _loadData(config) {
        const data = await super._loadData(config);
        await this._loadDocumentToRestore(config, data);
        return data;
    }
}

DocumentsListModel.Record = class DocumentsListRecord extends (
    DocumentsRecordMixin(ListModel.Record)
) {};
