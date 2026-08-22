/** @odoo-module native */
import { Component, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { DocumentFileUploader } from "../document_file_uploader/document_file_uploader.js";
import { defaultMoveTypeForJournal } from "../document_file_uploader/journal_defaults.js";

export class BillGuide extends Component {
    static template = "account.BillGuide";
    static components = {
        DocumentFileUploader,
    };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.context = null;
        this.alias = null;
        this.showSampleAction = false;
        onWillStart(this.onWillStart);
    }

    async onWillStart() {
        const rec = this.props.record;
        const ctx = this.env.searchModel.context;
        if (rec) {
            this.context = {
                default_journal_id: rec.resId,
                default_move_type: defaultMoveTypeForJournal(rec.data.type),
                active_model: rec.resModel,
                active_ids: [rec.resId],
            };
            this.alias = rec.data.alias_email || false;
        } else if (!ctx?.default_journal_id && ctx?.active_id) {
            this.context = {
                default_journal_id: ctx.active_id,
            };
        }
        this.showSampleAction = await this.orm.call(
            "account.journal",
            "is_sample_action_available",
        );
    }

    handleButtonClick(action, model = "account.journal") {
        this.action.doActionButton({
            resModel: model,
            name: action,
            context: this.context || this.env.searchModel.context,
            type: "object",
        });
    }

    openVendorBill() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            views: [[false, "form"]],
            context: this.context || this.env.searchModel.context,
        });
    }
}

export const billGuide = {
    component: BillGuide,
};

registry.category("view_widgets").add("bill_upload_guide", billGuide);
