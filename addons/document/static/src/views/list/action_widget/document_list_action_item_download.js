/** @odoo-module native */
import { documentActionRules } from "@document/views/document_action_rules";
import { _t } from "@web/core/translation";

import { DocumentsListActionItem } from "./document_list_action_item.js";

export class DocumentsListActionItemDownload extends DocumentsListActionItem {
    setup() {
        super.setup();
        this.icon = "fa-download";
        this.description = _t("Download");
    }

    get isVisible() {
        return documentActionRules.download(
            this.documentService,
            this.props.record.data,
        );
    }

    async onActionClicked() {
        await this.documentService.downloadDocuments([this.props.record]);
    }
}
