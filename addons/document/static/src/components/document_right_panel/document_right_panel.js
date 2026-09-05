/** @odoo-module native */
import { DocumentsChatter } from "@document/views/chatter/document_chatter";
import { useService } from "@web/core/utils/hooks";

import { DocumentsDetailsPanel } from "@document/components/document_details_panel/document_details_panel";

import { Component, useState } from "@odoo/owl";

export class DocumentsRightPanel extends Component {
    static template = "document.DocumentsViews.RightPanel";
    static props = {
        nbViewItems: { type: Number },
    };
    static components = {
        Chatter: DocumentsChatter,
        DocumentsDetailsPanel,
    };

    setup() {
        this.documentService = useService("document.document");
        this.state = useState(this.documentService.rightPanelReactive);
    }

    get panelDisabled() {
        return (
            !this.state.focusedRecord ||
            !this.state.focusedRecord.data ||
            typeof this.state.focusedRecord.data.id !== "number"
        );
    }
}
