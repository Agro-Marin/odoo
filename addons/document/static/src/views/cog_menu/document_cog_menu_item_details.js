/** @odoo-module native */
import { documentActionRules } from "@document/views/document_action_rules";
import { STATIC_COG_GROUP_ACTION_ADVANCED } from "./document_cog_menu_group.js";
import { DocumentsCogMenuItem } from "./document_cog_menu_item.js";
import { _t } from "@web/core/translation";

export class DocumentsCogMenuItemDetails extends DocumentsCogMenuItem {
    setup() {
        this.icon = "fa-solid fa-circle-info";
        this.label = _t("Info & Tags");
        super.setup();
    }

    async doActionOnFolder() {
        this.documentService.toggleRightPanelVisibility();
    }
}

export const documentsCogMenuItemDetails = {
    Component: DocumentsCogMenuItemDetails,
    groupNumber: STATIC_COG_GROUP_ACTION_ADVANCED,
    isDisplayed: (env) =>
        DocumentsCogMenuItem.isVisible(env, ({ documentService, folder }) =>
            documentActionRules.details(documentService, folder),
        ),
};
