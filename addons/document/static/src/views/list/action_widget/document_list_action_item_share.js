/** @odoo-module native */
import { documentActionRules } from "@document/views/document_action_rules";
import { _t } from "@web/core/translation";

import { DocumentsListActionItem } from "./document_list_action_item.js";

export class DocumentsListActionItemShare extends DocumentsListActionItem {
    setup() {
        super.setup();
        this.icon = "fa-user-plus";
        this.description = _t("Share");
    }

    get isVisible() {
        return (
            this.documentService.userIsInternal &&
            documentActionRules.share(this.documentService, this.props.record.data)
        );
    }

    async onActionClicked() {
        await this.documentService.openSharingDialog([this.props.record.data.id]);
    }
}
