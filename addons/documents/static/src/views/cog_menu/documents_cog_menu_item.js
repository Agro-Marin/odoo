/** @odoo-module native */
import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown";
import { useService } from "@web/core/utils/hooks";

/**
 * @param {Object} env
 * @param {Function|false} [isVisibleAdditional]
 * @returns {boolean}
 */
export function isDocumentsCogMenuItemVisible(
    { config, searchModel, services },
    isVisibleAdditional = false,
) {
    if (!(
        config &&
        searchModel &&
        searchModel.resModel === "documents.document" &&
        services
    )) {
        return false;
    }
    const folder = searchModel.getSelectedFolder();
    const documentService = services["document.document"];
    return Boolean(
        folder &&
        documentService &&
        ["kanban", "list"].includes(config.viewType) &&
        (!isVisibleAdditional ||
            isVisibleAdditional({ folder, config, searchModel, documentService })),
    );
}

export class DocumentsCogMenuItem extends Component {
    static template = "documents.DocumentCogMenuItem";
    static components = { DropdownItem };
    static props = {};

    static isVisible = isDocumentsCogMenuItemVisible;

    setup() {
        this.action = useService("action");
    }

    async onItemSelected() {
        const folder = this.env?.searchModel?.getSelectedFolder();
        if (!folder) {
            return;
        }
        await this.doActionOnFolder(folder);
    }

    async reload() {
        await this.env.searchModel._reloadSearchModel(true);
        await this.env.model.load();
        await this.env.model.notify();
    }

    async doActionOnFolder(folder) {}
}
