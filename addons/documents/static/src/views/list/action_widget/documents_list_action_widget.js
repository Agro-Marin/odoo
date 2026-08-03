/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets";

import { DocumentsListActionItemDetails } from "./documents_list_action_item_details.js";
import { DocumentsListActionItemDownload } from "./documents_list_action_item_download.js";
import { DocumentsListActionItemOpenFolder } from "./documents_list_action_item_open_folder.js";
import { DocumentsListActionItemRename } from "./documents_list_action_item_rename.js";
import { DocumentsListActionItemShare } from "./documents_list_action_item_share.js";

export class DocumentsListActionWidget extends Component {
    static props = { ...standardWidgetProps };
    static template = "documents.DocumentsListActionWidget";

    static actionItems = [
        DocumentsListActionItemShare,
        DocumentsListActionItemDownload,
        DocumentsListActionItemRename,
        DocumentsListActionItemDetails,
        DocumentsListActionItemOpenFolder,
    ];
}

export const documentsListActionWidget = {
    component: DocumentsListActionWidget,
};

registry.category("view_widgets").add("documents_list_actions", documentsListActionWidget);
