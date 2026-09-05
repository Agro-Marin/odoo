/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets";

export class DocumentsListActionItem extends Component {
    static template = "document.DocumentsListActionItem";
    static props = { ...standardWidgetProps };

    setup() {
        this.documentService = useService("document.document");
    }

    get isVisible() {
        return true;
    }

    async onActionClicked() {}
}
