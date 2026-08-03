/** @odoo-module native */
import { _t } from "@web/core/translation";

import { DocumentsListActionItem } from "./documents_list_action_item.js";

export class DocumentsListActionItemDetails extends DocumentsListActionItem {
    setup() {
        super.setup();
        this.icon = "fa-circle-info";
        this.description = _t("Details");
    }

    get isVisible() {
        return this.documentService.userIsInternal;
    }

    async onActionClicked() {
        if (this.documentService.focusedRecord.id !== this.props.record.id) {
            this.documentService.focusRecord(this.props.record);
            this.documentService.rightPanelReactive.visible ||
                this.documentService.toggleRightPanelVisibility();
        } else {
            this.documentService.toggleRightPanelVisibility();
        }
    }
}
