/** @odoo-module native */
import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown";
import { useService } from "@web/core/utils/hooks";

/**
 * Whether a documents cog-menu entry applies to the current env.
 *
 * Shared by {@link DocumentsCogMenuItem} and `DocumentCogMenuPinAction`, which
 * is not a `DocumentsCogMenuItem` (it renders a Dropdown, not a DropdownItem)
 * and therefore carried a byte-for-byte copy of this method.
 *
 * @param {Object} env the cog-menu env: `{ config, searchModel, services }`
 * @param {Function|false} [isVisibleAdditional] extra predicate, called with
 *   `{ folder, config, searchModel, documentService }`
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

/**
 * Allow to define a menu entry for the CogMenu by extending it.
 *
 * The sub classe must define:
 * - icon member variable (ex.: "fa-edit")
 * - label member variable (ex.: _t("Edit"))
 * - override the method doActionOnFolder (ex: to open the edit form)
 *
 * @extends Component
 */
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
