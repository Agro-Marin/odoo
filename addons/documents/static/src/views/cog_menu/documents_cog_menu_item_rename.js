/** @odoo-module native */
import { STATIC_COG_GROUP_ACTION_BASIC } from "./documents_cog_menu_group.js";
import { DocumentsCogMenuItem } from "./documents_cog_menu_item.js";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

export class DocumentsCogMenuItemRename extends DocumentsCogMenuItem {
    setup() {
        this.icon = "fa-solid fa-pen-to-square";
        this.label = _t("Rename");
        super.setup();
        this.documentService = useService("document.document");
    }

    async doActionOnFolder(folder) {
        await this.documentService.openDialogRename(folder.id);
        await this.reload();
    }
}

export const documentsCogMenuItemRename = {
    Component: DocumentsCogMenuItemRename,
    groupNumber: STATIC_COG_GROUP_ACTION_BASIC,
    isDisplayed: (env) =>
        DocumentsCogMenuItem.isVisible(env, ({ folder, documentService }) =>
            documentService.isEditable(folder)
        ),
};
