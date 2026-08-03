/** @odoo-module native */
import { Component, status, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { STATIC_COG_GROUP_ACTION_PIN } from "./documents_cog_menu_group.js";
import { Dropdown } from "@web/components/dropdown";
import { _t } from "@web/core/translation";
import { isDocumentsCogMenuItemVisible } from "./documents_cog_menu_item.js";

export class DocumentCogMenuPinAction extends Component {
    static template = "documents.DocumentCogMenuPinAction";
    static components = { Dropdown };
    static props = {};

    static isVisible = isDocumentsCogMenuItemVisible;

    setup() {
        this.action = useService("action");
        this.documentService = useService("document.document");
        this.notification = useService("notification");

        this.documentsState = useState({ actions: [], isLoading: true });
        // `useDebounced` rather than a bare `debounce`: the cog menu is a
        // dropdown, so it is routinely destroyed within the 1.5s window. The
        // uncancelled timer then fired `_reloadSearchModel` through the env of a
        // component that no longer exists, reloading the search panel behind the
        // user's back after they had closed the menu.
        this._reloadSearchModel = useDebounced(() => {
            this.env.searchModel._reloadSearchModel(true);
        }, 1500);

        const folderId = this.env.searchModel.getSelectedFolderId();
        this.documentService.getActions(folderId).then((actions) => {
            // Do not block `onWillStart` to not create a lag when opening the cogwheel
            if (status(this) === "destroyed") {
                return; // menu closed before the actions came back
            }
            this.documentsState.actions = actions;
            this.documentsState.isLoading = false;
        });
    }

    async onEnableAction(actionId) {
        const currentFolderId = this.env.searchModel.getSelectedFolderId();
        if (!currentFolderId || typeof currentFolderId !== "number") {
            this.notification.add(_t("You can not pin actions for that folder."), {
                type: "warning",
            });
            return;
        }

        // Toggle immediately the action to not create a lag (will be restored in "catch" if it fails)
        const action = this.documentsState.actions.find((a) => a.id === actionId);
        if (!action) {
            return; // the list was refreshed and no longer offers this action
        }
        action.is_embedded = !action.is_embedded;
        try {
            await this.documentService.enableAction(currentFolderId, actionId);
        } catch {
            action.is_embedded = !action.is_embedded;
        }
        this._reloadSearchModel();
    }
}

export const documentCogMenuPinAction = {
    Component: DocumentCogMenuPinAction,
    groupNumber: STATIC_COG_GROUP_ACTION_PIN,
    isDisplayed: (env) =>
        env.model.documentService.userIsDocumentUser &&
        DocumentCogMenuPinAction.isVisible(env, ({ folder, documentService }) =>
            documentService.isEditable(folder)
        )
};
