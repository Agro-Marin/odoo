/** @odoo-module native */
import { DocumentsAction } from "@document/views/action/document_action";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { DocumentsBreadcrumbs } from "@document/components/document_breadcrumbs";
import { DocumentsCogMenu } from "../cog_menu/document_cog_menu.js";
import { onPatched, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useViewModel } from "@web/model/model";
import { useSearchModel } from "@web/search/search_model";
import { useViewConfig } from "@web/core/view_config_hooks";

export class DocumentsControlPanel extends ControlPanel {
    static template = "document.ControlPanel";
    static components = {
        ...ControlPanel.components,
        DocumentsBreadcrumbs,
        DocumentsCogMenu,
        DocumentsAction,
    };

    setup() {
        super.setup();
        this.config = useViewConfig();
        this.searchModel = useSearchModel();
        this.model = useViewModel();
        this.ui = useService("ui");
        this.documentService = useService("document.document");

        this.rightPanelState = useState(this.documentService.rightPanelReactive);

        onPatched(() => {
            const searchPanelContainer = document.querySelector(".o_search_panel");
            if (searchPanelContainer) {
                searchPanelContainer.classList.toggle(
                    "d-none",
                    this.ui.isSmall && this.model.root.selection.length,
                );
            }
        });
    }

    get currentFolderId() {
        return this.searchModel.getSelectedFolderId();
    }

    get showActions() {
        const previewing = !!this.rightPanelState.previewedDocument;
        const focusing = !!this.rightPanelState.focusedRecord;
        const focusedSelected =
            focusing &&
            !!this.model.root.selection.find(
                (r) => r.id === this.rightPanelState.focusedRecord.id,
            );
        return (
            this.config.viewType !== "activity" &&
            !previewing &&
            (!focusing || focusedSelected)
        );
    }

    get pathBreadcrumbs() {
        if (this.model.config.context.active_model) {
            return [
                ...this.config.breadcrumbs.slice(0, -1),
                {
                    name: this.searchModel.getSelectedFolder().display_name,
                },
            ];
        }

        return this.searchModel
            .getSelectedFolderAndParents()
            .reverse()
            .map((folder) => {
                return {
                    jsId: folder.id,
                    name: folder.display_name,
                    onSelected: () => {
                        const folderSection = this.searchModel.getSections()[0];
                        this.searchModel.toggleCategoryValue(
                            folderSection.id,
                            folder.id,
                        );
                    },
                };
            });
    }
}
