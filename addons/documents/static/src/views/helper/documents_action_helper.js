/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { Component, markup, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";

export class DocumentsActionHelper extends Component {
    static template = "documents.DocumentsActionHelper";
    static props = [
        "noContentHelp",
    ];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            mailTo: undefined,
        });
        onWillStart(async () => {
            await this.updateShareInformation();
        });
        onWillUpdateProps(async () => {
            await this.updateShareInformation();
        });
    }

    get selectedFolderId() {
        return this.env.searchModel.getSelectedFolderId();
    }

    /**
     * @returns {markup}
     */
    get noContentHelp() {
        if (
            !this.selectedFolderId ||
            ["RECENT", "SHARED", "TRASH", "MY", "COMPANY"].includes(this.selectedFolderId)
        ) {
            const helpMessage = (() => {
                switch (this.selectedFolderId) {
                    case "TRASH":
                        return _t("Documents moved to trash will show up here");
                    case "RECENT":
                        return _t("Recently accessed Documents will show up here");
                    case "SHARED":
                        return _t("Documents shared with you will appear here");
                    case "MY":
                        return _t("Your personal space");
                    default:
                        return _t("Select a folder to upload a document");
                }
            })();
            return markup`<p class="o_view_nocontent_smiling_face">${helpMessage}</p>`;
        }
        return this.props.noContentHelp;
    }

    async updateShareInformation() {
        this.state.mailTo = undefined;
        const filteredDomain = this.env.searchModel.domain.filter(
            (leaf) => Array.isArray(leaf) && leaf.includes("folder_id")
        );
        if (filteredDomain.length !== 1 || typeof this.selectedFolderId !== "number") {
            return;
        }
        const selectedFolder = this.env.searchModel.getFolderById(this.selectedFolderId);
        if (
            !selectedFolder ||
            selectedFolder.user_permission === "none" ||
            !selectedFolder.alias_email
        ) {
            return;
        }
        this.state.mailTo = selectedFolder.alias_email;
    }
}
