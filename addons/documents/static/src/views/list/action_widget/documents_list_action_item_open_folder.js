/** @odoo-module native */
import { _t } from "@web/core/translation";

import { DocumentsListActionItem } from "./documents_list_action_item.js";

export class DocumentsListActionItemOpenFolder extends DocumentsListActionItem {
    setup() {
        super.setup();
        this.icon = "fa-solid fa-right-to-bracket";
        this.description = _t("Go inside");
    }

    get isVisible() {
        return this.props.record.data.type === "folder";
    }

    async onActionClicked() {
        return this.props.record.openFolder();
    }
}
