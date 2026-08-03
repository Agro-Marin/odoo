// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/pdf_viewer/pdf_viewer_field */

import {
    Component,
    onWillDestroy,
    onWillRender,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { useAction } from "@web/core/action_port";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";
import { url } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
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

    /** @type {import("@web/core/action_port").ActionPort} */
    action;
    /** @type {import("@odoo/owl").Ref} */
    iframeViewerPdfRef;
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {{ isValid: boolean; objectUrl: string }} */
    state;

    setup() {
        this.notification = useService("notification");
        this.action = useAction();
        this.state = useState({
            isValid: true,
            objectUrl: "",
        });
        this.iframeViewerPdfRef = useRef("iframeViewerPdf");
        let lastResId = this.props.record.resId;
        onWillRender(() => {
            const resId = this.props.record.resId;
            if (lastResId && resId !== lastResId) {
                this.setObjectUrl("");
                this.state.isValid = true;
            }
            lastResId = resId;
        });
        onWillUpdateProps((nextProps) => {
            if (nextProps.readonly) {
                this.setObjectUrl("");
            }
        });
        onWillDestroy(() => this.setObjectUrl(""));
        useEffect(
            (el) => {
                if (el) {
                    hidePDFJSButtons(el, {
                        hideDownload: true,
                        hidePrint: true,
                    });
                }
            },
            () => [this.iframeViewerPdfRef.el],
        );
    }

    /**
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
            return null;
        }
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
        this.setObjectUrl("");
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

/** @type {import("registries").FieldsRegistryItemShape} */
export const pdfViewerField = {
    component: PdfViewerField,
    displayName: _t("PDF Viewer"),
    supportedTypes: ["binary"],
    // Written on upload and compared against on every update; a value that is
    // never loaded makes that comparison always mismatch.
    //
    // `<name>_page` is the page the viewer opens on. It was read straight out of
    // `record.data` without ever being declared, so it was absent from every
    // record and the viewer always opened on page 1 -- the option could not work
    // even on a model that defines the field. `optional` makes the declaration a
    // no-op on the models that do not.
    fieldDependencies: ({ name, attrs }) => [
        ...(attrs.filename
            ? [{ name: attrs.filename, optional: true, written: true }]
            : []),
        { name: `${name}_page`, optional: true, readonly: true },
    ],
    extractProps: ({ attrs }) => ({ fileNameField: attrs.filename }),
};

registerField("pdf_viewer", pdfViewerField);
