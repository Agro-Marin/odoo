// @ts-check
/** @odoo-module native */

/** @module @web/components/file_viewer/file_viewer */

import { Component, onWillUpdateProps, useEffect, useRef, useState } from "@odoo/owl";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";
import { useThrottleForAnimation } from "@web/core/utils/timing";
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
        // Dragging fires far faster than the screen refreshes, and each call
        // measures the image and the viewport before writing a transform back.
        this.throttledUpdateZoomerStyle = useThrottleForAnimation(() =>
            this.updateZoomerStyle(),
        );
        onWillUpdateProps((nextProps) => this.onFilesUpdated(nextProps.files));
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
        if (!this.props.files.length) {
            return;
        }
        const last = this.props.files.length - 1;
        this.activateFile(this.state.index === last ? 0 : this.state.index + 1);
    }

    previous() {
        if (!this.props.files.length) {
            return;
        }
        const last = this.props.files.length - 1;
        this.activateFile(this.state.index === 0 ? last : this.state.index - 1);
    }

    /**
     * @param {Array<Object>} files
     */
    onFilesUpdated(files) {
        if (files === this.props.files) {
            return;
        }
        const index = this.state.file ? files.indexOf(this.state.file) : -1;
        if (index !== -1) {
            // Same file, it may only have moved.
            this.state.index = index;
            return;
        }
        // The file we were on is gone. Falling back on the index needs it to be
        // a real position: emptying the list parks it at -1, and comparing that
        // against a still-missing file used to read as "nothing changed", which
        // left the viewer blank for good once the list refilled.
        const fallback = Math.min(Math.max(this.state.index, 0), files.length - 1);
        this.activateFile(fallback, files);
    }

    /**
     * @param {number} index
     * @param {Array<Object>} [files]
     */
    activateFile(index, files = this.props.files) {
        this.state.index = index;
        this.state.file = files[index];
        this.state.scale = 1;
        this.state.angle = 0;
        this.state.imageLoaded = false;
        this.state.isIframeLoaded = false;
        this.translate = { dx: 0, dy: 0, x: 0, y: 0 };
    }

    onKeydown(ev) {
        if (!this.state.file) {
            return;
        }
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
        try {
            ev.target.setPointerCapture(ev.pointerId);
        } catch {}
    }

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
        this.throttledUpdateZoomerStyle();
    }

    onClickView() {
        if (this.didDrag) {
            this.didDrag = false;
            return;
        }
        this.close();
    }

    onClickImage() {
        this.didDrag = false;
    }

    resetZoom() {
        this.state.scale = 1;
        this.updateZoomerStyle();
    }

    rotate() {
        this.state.angle = (this.state.angle + 90) % 360;
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
        this.zoomerRef.el.style.setProperty("transform", `translate(${tx}px, ${ty}px)`);
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
        return style;
    }

    onClickPrint() {
        const printWindow = window.open();
        if (!printWindow) {
            return;
        }
        const image = printWindow.document.createElement("img");
        const printAndClose = () => {
            printWindow.print();
            printWindow.setTimeout(() => printWindow.close(), 10);
        };
        image.addEventListener("load", printAndClose, { once: true });
        image.addEventListener("error", printAndClose, { once: true });
        image.src = this.state.file.defaultSource;
        printWindow.document.body.appendChild(image);
    }
}
