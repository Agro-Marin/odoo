/** @odoo-module native */
import { DocumentsAction } from "@documents/views/action/documents_action";
import { useService } from "@web/core/utils/hooks";
import { FileViewer as WebFileViewer } from "@web/components/file_viewer";
import { onWillStart, onWillUpdateProps, reactive, useState } from "@odoo/owl";

export class FileViewer extends WebFileViewer {
    static template = "documents.FileViewer";
    static components = {
        DocumentsAction,
    };

    setup() {
        super.setup();
        /** @type {import("@documents/core/document_service").DocumentService} */
        this.documentService = useService("document.document");
        this.previewed = reactive(
            { document: this.documentService.documentList.documents[this.state.index] },
            async () => {
                this.documentService.setPreviewedDocument(this.previewed.document);
                if (this.state.file.isDocumentEmail) {
                    await this.state.file.loadDocumentEmailContent();
                } else if (this.state.file.isMimetypeTextual) {
                    await this.state.file.loadDocumentTextContent();
                }
            }
        );
        this.folderId = this.documentService.documentList?.folderId;
        this.rightPanelState = useState(this.documentService.rightPanelReactive);
        onWillUpdateProps((nextProps) => {
            const indexOfFileToPreview = nextProps.startIndex;
            if (
                indexOfFileToPreview !== this.state.index &&
                indexOfFileToPreview !== this.props.startIndex
            ) {
                this.activateFile(indexOfFileToPreview);
            }
            this.previewed.document =
                this.documentService.documentList.documents[nextProps.startIndex];
        });
        onWillStart(async () => {
            if (this.state.file.isDocumentEmail) {
                await this.state.file.loadDocumentEmailContent();
            } else if (this.state.file.isMimetypeTextual) {
                await this.state.file.loadDocumentTextContent();
            }
        });
    }

    get isChatterButtonVisible() {
        return this.documentService.userIsInternal && !this.env.isSmall;
    }

    close() {
        this.documentService.documentList?.onDeleteCallback();
        this.previewed.document = null;
        super.close();
    }

    next() {
        super.next();
        this.previewed.document = this.documentService.documentList.documents[this.state.index];
    }

    previous() {
        super.previous();
        this.previewed.document = this.documentService.documentList.documents[this.state.index];
    }
}
