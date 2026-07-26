/** @odoo-module native */
import { ActivityModel } from "@mail/views/web/activity/activity_model";
import { DocumentsModelMixin } from "../documents_model_mixin.js";
import { DocumentsRecordMixin } from "../documents_record_mixin.js";

export class DocumentsActivityModel extends DocumentsModelMixin(ActivityModel) {}

DocumentsActivityModel.Record = class DocumentsActivityRecord extends (
    DocumentsRecordMixin(ActivityModel.Record)
) {};
