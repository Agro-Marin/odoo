// @ts-check
/** @odoo-module native */

/** @module @web/components/file_viewer/file_viewer - Full-screen image, PDF, video, and text file preview with navigation controls */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";
/**
 * @typedef {Object} File
 * @property {string} name
 * @property {string} downloadUrl
 * @property {boolean} [isImage]
 * @property {boolean} [isPdf]
 * @property {boolean} [isVideo]
 * @property {boolean} [isText]
 * @property {string} [defaultSource]
 * @property {boolean} [isUrlYoutube]
 * @property {string} [mimetype]
 * @property {boolean} [isViewable]
 * @typedef {Object} Props
 * @property {Array<File>} files
 * @property {number} startIndex
 * @property {function} close
 * @property {boolean} [modal]
 * @extends {Component<Props>}
 */
export class FileViewer extends Component {
    static template = "web.FileViewer";
    static components = {};
    static props = ["files", "startIndex", "close?", "modal?"];
    static defaultProps = {
        modal: true,
    };

    setup() {
        useAutofocus();
        this.imageRef = useRef("image");
        this.zoomerRef = useRef("zoomer");
        this.iframeViewerPdfRef = useRef("iframeViewerPdf");

        this.isDragging = false;
        this.didDrag = false;
        this.dragStartX = 0;
        this.dragStartY = 0;

        this.scrollZoomStep = 0.1;
        this.zoomStep = 0.5;
        this.minScale = 0.5;
        this.translate = {
            dx: 0,
            dy: 0,
            x: 0,
            y: 0,
        };

        this.state = useState({
            index: this.props.startIndex,
            file: this.props.files[this.props.startIndex],
            imageLoaded: false,
            scale: 1,
            angle: 0,
            isIframeLoaded: false,
        });
        this.ui = useService("ui");
        useEffect(
            (el) => {
                if (el) {
                    hidePDFJSButtons(this.iframeViewerPdfRef.el, {
                        hideDownload: true,
                    });
                }
            },
            () => [this.iframeViewerPdfRef.el],
        );
    }

    onImageLoaded() {
        this.state.imageLoaded = true;
    }

    onIframeLoaded(ev) {
        const iFrameEl = ev.target;
        iFrameEl.contentWindow.requestAnimationFrame(() => {
            this.state.isIframeLoaded = true;
        });
    }

    close() {
        this.props.close && this.props.close();
    }

    next() {
        const last = this.props.files.length - 1;
        this.activateFile(this.state.index === last ? 0 : this.state.index + 1);
    }

    previous() {
        const last = this.props.files.length - 1;
        this.activateFile(this.state.index === 0 ? last : this.state.index - 1);
    }

    activateFile(index) {
        this.state.index = index;
        this.state.file = this.props.files[index];
        this.state.scale = 1;
        this.state.angle = 0;
        this.state.imageLoaded = false;
        this.state.isIframeLoaded = false;
        this.translate = { dx: 0, dy: 0, x: 0, y: 0 };
    }

    onKeydown(ev) {
        switch (ev.key) {
            case "ArrowRight":
                this.next();
                break;
            case "ArrowLeft":
                this.previous();
                break;
            case "Escape":
                this.close();
                break;
            case "q":
                this.close();
                break;
        }
        if (this.state.file.isImage) {
            switch (ev.key) {
                case "r":
                    this.rotate();
                    break;
                case "+":
                    this.zoomIn();
                    break;
                case "-":
                    this.zoomOut();
                    break;
                case "0":
                    this.resetZoom();
                    break;
            }
        }
    }

    /**
     * @param {WheelEvent} ev
     */
    onWheelImage(ev) {
        if (ev.deltaY > 0) {
            this.zoomOut({ scroll: true });
        } else {
            this.zoomIn({ scroll: true });
        }
    }

    /**
     * @param {PointerEvent} ev
     */
    onPointerdownImage(ev) {
        if (this.isDragging) {
            return;
        }
        if (ev.button !== 0) {
            return;
        }
        this.isDragging = true;
        this.didDrag = false;
        this.dragStartX = ev.clientX;
        this.dragStartY = ev.clientY;
        // Capture the pointer so move/up keep flowing during the pan even if
        // it leaves the image. Untrusted (test) pointers can't be captured —
        // the main view's pointerup handler still ends the drag then.
        try {
            ev.target.setPointerCapture(ev.pointerId);
        } catch {
            // no active pointer to capture (synthetic event)
        }
    }

    /**
     * Ends an image pan. Bound on the main view (pointerup/pointercancel) so it
     * fires whether or not the pointer was captured by the image.
     */
    onPointerupView() {
        if (!this.isDragging) {
            return;
        }
        this.isDragging = false;
        this.translate.x += this.translate.dx;
        this.translate.y += this.translate.dy;
        this.translate.dx = 0;
        this.translate.dy = 0;
        this.updateZoomerStyle();
    }

    /**
     * @param {PointerEvent} ev
     */
    onPointermoveView(ev) {
        if (!this.isDragging) {
            return;
        }
        this.translate.dx = ev.clientX - this.dragStartX;
        this.translate.dy = ev.clientY - this.dragStartY;
        if (this.translate.dx || this.translate.dy) {
            this.didDrag = true;
        }
        this.updateZoomerStyle();
    }

    /**
     * The click composed at the end of an image pan released over the main
     * view must not close the viewer; only a genuine click does.
     */
    onClickView() {
        if (this.didDrag) {
            this.didDrag = false;
            return;
        }
        this.close();
    }

    /**
     * Consumes a drag-end click landing on the image (its `.stop` keeps it
     * from the main view) so the next genuine click still closes the viewer.
     */
    onClickImage() {
        this.didDrag = false;
    }

    resetZoom() {
        this.state.scale = 1;
        this.updateZoomerStyle();
    }

    rotate() {
        this.state.angle += 90;
    }

    /**
     * @param {{ scroll?: boolean }} options
     */
    zoomIn({ scroll = false } = {}) {
        this.state.scale =
            this.state.scale + (scroll ? this.scrollZoomStep : this.zoomStep);
        this.updateZoomerStyle();
    }

    /**
     * @param {{ scroll?: boolean }} options
     */
    zoomOut({ scroll = false } = {}) {
        if (this.state.scale === this.minScale) {
            return;
        }
        const unflooredAdaptedScale =
            this.state.scale - (scroll ? this.scrollZoomStep : this.zoomStep);
        this.state.scale = Math.max(this.minScale, unflooredAdaptedScale);
        this.updateZoomerStyle();
    }

    updateZoomerStyle() {
        if (!this.imageRef.el || !this.zoomerRef.el) {
            return;
        }
        const tx =
            this.imageRef.el.offsetWidth * this.state.scale >
            this.zoomerRef.el.offsetWidth
                ? this.translate.x + this.translate.dx
                : 0;
        const ty =
            this.imageRef.el.offsetHeight * this.state.scale >
            this.zoomerRef.el.offsetHeight
                ? this.translate.y + this.translate.dy
                : 0;
        if (tx === 0) {
            this.translate.x = 0;
        }
        if (ty === 0) {
            this.translate.y = 0;
        }
        this.zoomerRef.el.style.cssText = "transform: " + `translate(${tx}px, ${ty}px)`;
    }

    get imageStyle() {
        let style =
            "transform: " +
            `scale3d(${this.state.scale}, ${this.state.scale}, 1) ` +
            `rotate(${this.state.angle}deg);`;

        if (this.state.angle % 180 !== 0) {
            style += `max-height: ${window.innerWidth}px; max-width: ${window.innerHeight}px;`;
        } else {
            style += "max-height: 100%; max-width: 100%;";
        }
        style += `background: repeating-conic-gradient(#ccc 0deg 90deg, #fff 90deg 180deg) 50% / 20px 20px;`;
        return style;
    }

    onClickPrint() {
        const printWindow = window.open();
        if (!printWindow) {
            return;
        }
        const image = printWindow.document.createElement("img");
        image.setAttribute("onload", "window.print(); setTimeout(window.close, 10)");
        image.setAttribute("onerror", "window.print(); setTimeout(window.close, 10)");
        image.src = this.state.file.defaultSource;
        printWindow.document.body.appendChild(image);
    }
}
