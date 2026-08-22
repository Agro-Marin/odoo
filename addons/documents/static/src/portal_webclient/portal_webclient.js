/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { ActionContainer } from "@web/webclient/actions";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { Component, onMounted } from "@odoo/owl";

export class PortalWebclientWebClient extends Component {
    static props = {};
    static components = { ActionContainer, MainComponentsContainer };
    static template = "documents.PortalWebclientWebClient";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.view = useService("view");
        this.documentService = useService("document.document");
        const initData = this.documentService.initData;
        onMounted(async () => {
            const action = await this.action.loadAction("documents.document_action_portal");
            action.path = "documents";
            this.action.doAction(action, {
                additionalContext: initData.userFolderId
                    ? { searchpanel_default_user_folder_id: initData.userFolderId }
                    : {},
                stackPosition: "replaceCurrentAction",
            });
        });
    }
}
