/** @odoo-module native */
import { STATIC_COG_GROUP_ACTION_ADVANCED } from "./documents_cog_menu_group.js";
import { DocumentsCogMenuItem } from "./documents_cog_menu_item.js";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * Add shortcut of selected folder menu entry.
 *
 * @extends Component
 */
export class DocumentsCogMenuItemShortcut extends DocumentsCogMenuItem {
    setup() {
        this.icon = "fa-solid fa-up-right-from-square";
        this.label = _t("Add shortcut");
        super.setup();
        this.documentService = useService("document.document");
    }

    async doActionOnFolder(folder) {
        await this.documentService.openOperationDialog({
            documents: [{ id: folder.id, name: folder.display_name }],
            operation: "shortcut",
            onClose: () => this.reload(),
        });
        await this.reload();
    }
}

export const documentsCogMenuItemShortcut = {
    Component: DocumentsCogMenuItemShortcut,
    groupNumber: STATIC_COG_GROUP_ACTION_ADVANCED,
    isDisplayed: (env) =>
        DocumentsCogMenuItem.isVisible(
            env,
            ({ folder, documentService }) =>
                documentService.isEditable(folder) &&
                !folder.shortcut_document_id &&
                typeof folder.folder_id === "number"
        ),
};
