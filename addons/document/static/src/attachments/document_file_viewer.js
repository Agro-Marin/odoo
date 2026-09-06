/** @odoo-module native */
import { DocumentsAction } from "@document/views/action/document_action";
import { useService } from "@web/core/utils/hooks";
import { FileViewer as WebFileViewer } from "@web/components/file_viewer";
import { onWillStart, onWillUpdateProps, reactive, useState } from "@odoo/owl";

export class DocumentsFileViewer extends WebFileViewer {
    static template = "document.FileViewer";
    static components = {
        DocumentsAction,
    };

    setup() {
        super.setup();
        /** @type {import("@document/core/document_service").DocumentService} */
        this.documentService = useService("document.document");
        this.previewed = reactive(
            { document: this.documentService.documentList.documents[this.state.index] },
            async () => {
                this.documentService.setPreviewedDocument(this.previewed.document);
                await this._loadFileContent();
            },
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
        onWillStart(() => this._loadFileContent());
    }

    /** Email and textual files are fetched on demand; the others are streamed. */
    async _loadFileContent() {
        if (this.state.file.isDocumentEmail) {
            await this.state.file.loadDocumentEmailContent();
        } else if (this.state.file.isMimetypeTextual) {
            await this.state.file.loadDocumentTextContent();
        }
    }

    _syncPreviewedDocument() {
        this.previewed.document =
            this.documentService.documentList.documents[this.state.index];
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
        this._syncPreviewedDocument();
    }

    previous() {
        super.previous();
        this._syncPreviewedDocument();
    }
}
