/** @odoo-module native */
import { documentActionRules } from "@document/views/document_action_rules";
import { _t } from "@web/core/translation";

import { DocumentsListActionItem } from "./document_list_action_item.js";
import { useViewModel } from "@web/model/model";

export class DocumentsListActionItemRename extends DocumentsListActionItem {
    setup() {
        super.setup();
        this.model = useViewModel();
        this.icon = "fa-edit";
        this.description = _t("Rename");
    }

    get isVisible() {
        return documentActionRules.rename(this.documentService, this.props.record.data);
    }

    async onActionClicked() {
        await this.documentService.openDialogRename(this.props.record.data.id);
        await this.model._notifyChange();
    }
}
