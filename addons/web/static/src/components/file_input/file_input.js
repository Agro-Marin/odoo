// @ts-check
/** @odoo-module native */

/** @module @web/components/file_input/file_input - Customizable file upload input with route-based server upload and multi-file support */

import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { useFileUploader } from "@web/core/utils/files";
/**
 * Customizable file input; the default t-slot content is the trigger that
 * opens the file upload prompt.
 * @extends Component
 * @param {string} [props.acceptedFileExtensions='*'] Comma-separated list of authorized file extensions (default to all).
 * @param {string} [props.route='/web/binary/upload_attachment'] Route called when a file is uploaded.
 * @param {string} [props.resId]
 * @param {string} [props.resModel]
 * @param {string} [props.multiUpload=false] Whether to allow uploading multiple files at once.
 */
export class FileInput extends Component {
    static template = "web.FileInput";
    static defaultProps = {
        acceptedFileExtensions: "*",
        hidden: false,
        multiUpload: false,
        onUpload: () => {},
        route: "/web/binary/upload_attachment",
        beforeOpen: async () => true,
    };
    static props = {
        acceptedFileExtensions: { type: String, optional: true },
        autoOpen: { type: Boolean, optional: true },
        hidden: { type: Boolean, optional: true },
        multiUpload: { type: Boolean, optional: true },
        onUpload: { type: Function, optional: true },
        onWillUploadFiles: { type: Function, optional: true },
        beforeOpen: { type: Function, optional: true },
        resId: { type: Number, optional: true },
        resModel: { type: String, optional: true },
        route: { type: String, optional: true },
        "*": true,
    };

    setup() {
        this.uploadFiles = useFileUploader();
        this.fileInputRef = useRef("file-input");
        this.state = useState({
            // Disables upload button if currently uploading.
            isDisable: false,
        });

        onMounted(() => {
            if (this.props.autoOpen) {
                this.onTriggerClicked();
            }
        });
    }

    get httpParams() {
        const { resId, resModel } = this.props;
        const params = {
            csrf_token: odoo.csrf_token,
            ufile: [.../** @type {HTMLInputElement} */ (this.fileInputRef.el).files],
        };
        if (resModel) {
            params.model = resModel;
        }
        if (resId !== undefined) {
            params.id = resId;
        }
        return params;
    }

    // Handlers

    /** Upload the input's files to `route`, tagged with the record's model/id if set. */
    async onFileInputChange() {
        this.state.isDisable = true;
        const httpParams = this.httpParams;
        if (this.props.onWillUploadFiles) {
            try {
                const files = await this.props.onWillUploadFiles(httpParams.ufile);
                httpParams.ufile = files;
            } catch (e) {
                this.state.isDisable = false;
                throw e;
            }
        }
        try {
            const parsedFileData = await this.uploadFiles(this.props.route, httpParams);
            if (parsedFileData) {
                // Also pass the raw files so onUpload can read metadata like names.
                this.props.onUpload(
                    parsedFileData,
                    this.fileInputRef.el
                        ? /** @type {HTMLInputElement} */ (this.fileInputRef.el).files
                        : [],
                );
            }
        } finally {
            // The input won't fire this handler again for the same file name unless
            // its value is cleared first — even on failure, so retry is possible.
            if (this.fileInputRef.el) {
                /** @type {HTMLInputElement} */ (this.fileInputRef.el).value = "";
            }
            this.state.isDisable = false;
        }
    }

    async onTriggerClicked() {
        if (await this.props.beforeOpen()) {
            this.fileInputRef.el.click();
        }
    }
}
