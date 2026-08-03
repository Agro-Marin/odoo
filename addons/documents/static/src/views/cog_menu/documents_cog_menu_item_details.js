/** @odoo-module native */
import { STATIC_COG_GROUP_ACTION_ADVANCED } from "./documents_cog_menu_group.js";
import { DocumentsCogMenuItem } from "./documents_cog_menu_item.js";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/translation";

export class DocumentsCogMenuItemDetails extends DocumentsCogMenuItem {
    setup() {
        this.icon = "fa-solid fa-circle-info";
        this.label = _t("Info & Tags");
        this.documentService = useService("document.document");
        super.setup();
    }

    async doActionOnFolder(folder) {
        this.documentService.toggleRightPanelVisibility();
    }
}

export const documentsCogMenuItemDetails = {
    Component: DocumentsCogMenuItemDetails,
    groupNumber: STATIC_COG_GROUP_ACTION_ADVANCED,
    isDisplayed: (env) =>
        DocumentsCogMenuItem.isVisible(
            env,
            ({ documentService, folder }) =>
                documentService.userIsInternal && typeof folder.id === "number"
        ),
};
