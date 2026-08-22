/** @odoo-module native */
import { _t } from "@web/core/translation";
import { ActivityController } from "@mail/views/web/activity/activity_controller";

import { preSuperSetup, useDocumentView } from "@documents/views/hooks";
import { useState } from "@odoo/owl";

export class DocumentsActivityController extends ActivityController {
    static template = "documents.DocumentsActivityController";
    setup() {
        preSuperSetup();
        super.setup(...arguments);
        const properties = useDocumentView(this.documentsViewHelpers());
        Object.assign(this, properties);

        this.documentStates = useState({
            previewStore: {},
        });
    }

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

    documentsViewHelpers() {
        return {
            getSelectedDocumentsElements: () => [],
            isRecordPreviewable: this.isRecordPreviewable.bind(this),
            setPreviewStore: (previewStore) => {
                this.documentStates.previewStore = previewStore;
            },
        };
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
