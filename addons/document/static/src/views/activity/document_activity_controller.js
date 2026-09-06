/** @odoo-module native */
import { _t } from "@web/core/translation";
import { ActivityController } from "@mail/views/web/activity/activity_controller";

import { DocumentsControllerMixin } from "@document/views/document_controller_mixin";

export class DocumentsActivityController extends DocumentsControllerMixin(
    ActivityController,
) {
    static template = "document.DocumentsActivityController";

    get rendererProps() {
        const props = super.rendererProps;
        props.previewStore = this.documentStates.previewStore;
        return props;
    }

    get modelParams() {
        const modelParams = super.modelParams;
        modelParams.multiEdit = true;
        return modelParams;
    }

    /**
     * @override
     */
    async openRecord(record) {
        for (const record of this.model.root.selection) {
            record.selected = false;
        }
        record.selected = true;
        this.model.notify();
    }

    /**
     * @returns {Boolean}
     */
    isRecordPreviewable(record) {
        return this.model.activityData.activity_res_ids.includes(record.resId);
    }

    /**
     * @override
     * @param {number} [templateID]
     * @param {number} [activityTypeID]
     */
    sendMailTemplate(templateID, activityTypeID) {
        super.sendMailTemplate(templateID, activityTypeID);
        this.env.services.notification.add(_t("Reminder emails have been sent."), {
            type: "success",
        });
    }
}
