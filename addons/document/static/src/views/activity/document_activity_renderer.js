/** @odoo-module native */
import { ActivityRenderer } from "@mail/views/web/activity/activity_renderer";

import { DocumentsRightPanel } from "@document/components/document_right_panel/document_right_panel";
import { DocumentsRendererMixin } from "@document/views/document_renderer_mixin";
import { DocumentsFileViewerHost } from "@document/views/helper/document_file_viewer";

import { onWillUpdateProps, useRef } from "@odoo/owl";

export class DocumentsActivityRenderer extends DocumentsRendererMixin(
    ActivityRenderer,
) {
    static props = {
        ...ActivityRenderer.props,
        previewStore: Object,
    };
    static template = "document.DocumentsActivityRenderer";
    static components = {
        ...ActivityRenderer.components,
        DocumentsRightPanel,
        DocumentsFileViewerHost,
    };

    setup() {
        super.setup();
        this.root = useRef("root");

        onWillUpdateProps((nextProps) => {
            const selectedRecord = nextProps.records.find((r) => r.selected);
            if (selectedRecord) {
                this.documentService.focusRecord(selectedRecord);
            }
        });
    }
}
