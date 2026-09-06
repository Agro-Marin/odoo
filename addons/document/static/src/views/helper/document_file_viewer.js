/** @odoo-module native */
import { DocumentsFileViewer } from "@document/attachments/document_file_viewer";
import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/** Fixed-position host of the viewer inside a documents view. */
export class DocumentsFileViewerHost extends Component {
    static template = "document.DocumentsFileViewer";
    static components = {
        DocumentsFileViewer,
    };
    static props = ["parentRoot", "previewStore"];

    setup() {
        this.documentService = useService("document.document");
        this.root = useRef("root");
        this.rightPanelState = useState(this.documentService.rightPanelReactive);
        this.state = useState({ topOffset: 0 });

        const onKeydown = this.onIframeKeydown.bind(this);
        useEffect(
            (iframe) => {
                if (!iframe) {
                    return;
                }
                const onLoad = () => {
                    if (!iframe.contentDocument) {
                        return;
                    }
                    iframe.contentDocument.addEventListener("keydown", onKeydown);
                };
                iframe.addEventListener("load", onLoad);
                return () => {
                    iframe.removeEventListener("load", onLoad);
                };
            },
            () => [this.root.el && this.root.el.querySelector("iframe")],
        );
        useEffect(
            (el) => {
                if (!el) {
                    return;
                }
                this.state.topOffset = el.scrollTop;
                const scrollHandler = () => {
                    this.state.topOffset = el.scrollTop;
                };
                el.addEventListener("scroll", scrollHandler);
                return () => {
                    el.removeEventListener("scroll", scrollHandler);
                };
            },
            () => [this.parentRoot.el],
        );
    }

    get parentRoot() {
        return this.props.parentRoot;
    }

    get isRightPanelVisible() {
        return this.rightPanelState.visible && !this.env.isSmall;
    }

    onGlobalKeydown(ev) {
        const cancelledKeys = ["ArrowUp", "ArrowDown"];
        if (cancelledKeys.includes(ev.key)) {
            ev.stopPropagation();
        }
    }

    onIframeKeydown(ev) {
        if (ev.key === "Escape") {
            this.env.documentsView.bus.trigger("documents-close-preview");
        }
    }
}
