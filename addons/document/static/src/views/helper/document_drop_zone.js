/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { useService } from "@web/core/utils/hooks";
import { useSearchModel } from "@web/search/search_model";
import { useDocumentContext } from "@document/document_context";

export class DocumentsDropZone extends Component {
    static template = "document.DocumentsDropZone";
    static props = ["parentRoot"];

    setup() {
        this.documentContext = useDocumentContext();
        this.searchModel = useSearchModel();
        this.state = useState({
            dragOver: false,
            topOffset: 0,
        });
        this.documentService = useService("document.document");
        useLayoutEffect(
            (el) => {
                if (!el) {
                    return;
                }
                this.state.topOffset = el.scrollTop;
                const overHandler = this.onDragOver.bind(this);
                const leaveHandler = this.onDragLeave.bind(this);
                const scrollHandler = () => {
                    this.state.topOffset = el.scrollTop;
                };
                el.addEventListener("dragover", overHandler);
                el.addEventListener("dragleave", leaveHandler);
                el.addEventListener("scroll", scrollHandler);
                return () => {
                    el.removeEventListener("dragover", overHandler);
                    el.removeEventListener("dragleave", leaveHandler);
                    el.removeEventListener("scroll", scrollHandler);
                };
            },
            () => [this.props.parentRoot.el],
        );
    }

    get root() {
        return this.props.parentRoot;
    }

    get canDrop() {
        return this.documentService.canUploadInFolder(
            this.searchModel.getSelectedFolder(),
        );
    }

    get rootDropOverClass() {
        return this.canDrop
            ? "o_documents_drop_over"
            : "o_documents_drop_over_unauthorized";
    }

    onDragOver(ev) {
        if (!ev.dataTransfer.types.includes("Files")) {
            return;
        }
        ev.stopPropagation();
        ev.preventDefault();

        this.root?.el?.classList.toggle(this.rootDropOverClass, true);
        this.state.dragOver = true;
    }

    onDragLeave(ev) {
        ev.stopPropagation();
        ev.preventDefault();

        this.root?.el?.classList.remove(this.rootDropOverClass);
        this.state.dragOver = false;
    }

    onDrop(ev) {
        if (!ev.dataTransfer.types.includes("Files")) {
            return;
        }

        this.root?.el?.classList.remove(this.rootDropOverClass);
        this.state.dragOver = false;
        if (this.canDrop) {
            this.documentContext.documentsView.bus.trigger("documents-upload-files", {
                files: ev.dataTransfer.files,
                accessToken: this.documentService.currentFolderAccessToken,
            });
        }
    }
}
