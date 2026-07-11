// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/pdf_viewer/pdf_viewer_field - Embedded PDF viewer field for Binary columns using PDF.js */

import {
    Component,
    onWillDestroy,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";
import { url } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import { FileUploader } from "@web/fields/file_handler";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class PdfViewerField extends Component {
    static template = "web.PdfViewerField";
    static components = {
        FileUploader,
    };
    static props = {
        ...standardFieldProps,
        fileNameField: { type: String, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({
            isValid: true,
            objectUrl: "",
        });
        this.iframeViewerPdfRef = useRef("iframeViewerPdf");
        onWillUpdateProps((nextProps) => {
            if (nextProps.readonly) {
                this.setObjectUrl("");
            }
        });
        onWillDestroy(() => this.setObjectUrl(""));
        useEffect(
            (el) => {
                if (el) {
                    hidePDFJSButtons(this.iframeViewerPdfRef.el, {
                        hideDownload: true,
                        hidePrint: true,
                    });
                }
            },
            () => [this.iframeViewerPdfRef.el],
        );
    }

    /**
     * Replaces the current object URL, revoking the previous one so the
     * underlying blob doesn't leak.
     * @param {string} objectUrl
     */
    setObjectUrl(objectUrl) {
        if (this.state.objectUrl && this.state.objectUrl !== objectUrl) {
            URL.revokeObjectURL(this.state.objectUrl);
        }
        this.state.objectUrl = objectUrl;
    }

    get urlFile() {
        return (
            this.state.objectUrl ||
            url("/web/content", {
                model: this.props.record.resModel,
                field: this.props.name,
                id: this.props.record.resId,
            })
        );
    }

    get url() {
        if (!this.state.isValid || !this.props.record.data[this.props.name]) {
            return null;
        }
        if (!this.state.objectUrl && !this.props.record.resId) {
            // Unsaved record without a fresh upload (e.g. a duplicated record):
            // /web/content?...&id=false would render a broken frame.
            return null;
        }
        // By convention, an optional sibling `<name>_page` field selects the
        // page to open (not declared in fieldDependencies: it is view-provided).
        const page = this.props.record.data[`${this.props.name}_page`] || 1;
        const file = encodeURIComponent(this.urlFile);
        return `/web/static/lib/pdfjs/web/viewer.html?file=${file}#page=${page}`;
    }

    update({ name, data }) {
        const changes = {
            [this.props.name]: data || false,
        };
        if (
            this.props.fileNameField &&
            this.props.record.data[this.props.fileNameField] !== name
        ) {
            changes[this.props.fileNameField] = name || false;
        }
        return this.props.record.update(changes);
    }

    onFileRemove() {
        this.state.isValid = true;
        this.update(/** @type {any} */ ({}));
    }

    onFileDownload() {
        this.action.doAction({
            type: "ir.actions.act_url",
            url: this.urlFile,
            target: "new",
        });
    }

    onFileUploaded({ name, data, objectUrl }) {
        this.state.isValid = true;
        this.setObjectUrl(objectUrl);
        this.update({ name, data });
    }

    onLoadFailed() {
        this.state.isValid = false;
        this.notification.add(_t("Could not display the selected pdf"), {
            type: "danger",
        });
    }
}

export const pdfViewerField = {
    component: PdfViewerField,
    displayName: _t("PDF Viewer"),
    supportedTypes: ["binary"],
    extractProps: ({ attrs }) => ({ fileNameField: attrs.filename }),
};

registerField("pdf_viewer", pdfViewerField);
