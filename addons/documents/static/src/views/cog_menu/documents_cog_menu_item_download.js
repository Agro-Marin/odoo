/** @odoo-module native */
import { STATIC_COG_GROUP_ACTION_BASIC } from "./documents_cog_menu_group.js";
import { DocumentsCogMenuItem } from "./documents_cog_menu_item.js";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

export class DocumentsCogMenuItemDownload extends DocumentsCogMenuItem {
    setup() {
        this.icon = "fa-solid fa-download";
        this.label = _t("Download");
        super.setup();
        this.action = useService("action");
    }

    async doActionOnFolder(folder) {
        this.action.doAction({
            type: "ir.actions.act_url",
            url: `/documents/content/${encodeURIComponent(folder.access_token)}`,
        });
    }
}

export const documentsCogMenuItemDownload = {
    Component: DocumentsCogMenuItemDownload,
    groupNumber: STATIC_COG_GROUP_ACTION_BASIC,
    isDisplayed: (env) =>
        DocumentsCogMenuItem.isVisible(env, ({ folder, documentService }) =>
            documentService.canDownload(folder)
        ),
};
