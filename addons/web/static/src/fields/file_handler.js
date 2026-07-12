// @ts-check
/** @odoo-module native */

/** @module @web/fields/file_handler - FileUploader component for handling file input, validation, and base64 conversion */

import { Component, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { checkFileSize } from "@web/core/utils/files";
import { useService } from "@web/core/utils/hooks";
import { getDataURLFromFile } from "@web/core/utils/urls";
export class FileUploader extends Component {
    static template = "web.FileUploader";
    static props = {
        onClick: { type: Function, optional: true },
        onUploaded: Function,
        onUploadComplete: { type: Function, optional: true },
        multiUpload: { type: Boolean, optional: true },
        checkSize: { type: Boolean, optional: true },
        inputName: { type: String, optional: true },
        fileUploadClass: { type: String, optional: true },
        acceptedFileExtensions: { type: String, optional: true },
        slots: { type: Object, optional: true },
        showUploadingText: { type: Boolean, optional: true },
        // See https://www.iana.org/assignments/media-types/media-types.xhtml
        allowedMIMETypes: { type: String, optional: true },
        // Opt-in: mint a blob object URL for each uploaded PDF and pass it
        // as `objectUrl` to `onUploaded`. Ownership transfers to the
        // consumer, which MUST revoke it (see PdfViewerField). Kept opt-in
        // because a URL handed to a consumer that ignores it pins the whole
        // file in memory until page unload.
        createObjectUrl: { type: Boolean, optional: true },
    };
    static defaultProps = {
        checkSize: true,
        showUploadingText: true,
        createObjectUrl: false,
    };

    setup() {
        this.notification = useService("notification");
        this.fileInputRef = useRef("fileInput");
        this.state = useState({
            isUploading: false,
        });
    }

    /**
     * @param {Event} ev
     */
    async onFileChange(ev) {
        const inputEl = /** @type {HTMLInputElement} */ (ev.target);
        const files = [...inputEl.files].filter((file) => this.validFileType(file));
        if (!files.length) {
            // Reset so re-selecting the same file still fires a "change" event.
            inputEl.value = "";
            return;
        }
        try {
            for (const file of files) {
                if (
                    this.props.checkSize &&
                    !checkFileSize(file.size, this.notification)
                ) {
                    // Skip this file but keep processing the rest of a multi-upload.
                    continue;
                }
                this.state.isUploading = true;
                try {
                    const data = await getDataURLFromFile(file);
                    if (!file.size) {
                        console.warn(`Error while uploading file : ${file.name}`);
                        this.notification.add(
                            _t("There was a problem while uploading your file."),
                            {
                                type: "danger",
                            },
                        );
                        continue;
                    }
                    await this.props.onUploaded({
                        name: file.name,
                        size: file.size,
                        type: file.type,
                        data: data.split(",")[1],
                        objectUrl:
                            this.props.createObjectUrl &&
                            file.type === "application/pdf"
                                ? URL.createObjectURL(file)
                                : null,
                    });
                } finally {
                    this.state.isUploading = false;
                }
            }
        } finally {
            // Always reset, even on failure, so re-selecting the same file
            // still fires a "change" event.
            inputEl.value = "";
        }
        if (this.props.multiUpload && this.props.onUploadComplete) {
            this.props.onUploadComplete({});
        }
    }

    /**
     * `allowedMIMETypes` restricts selectable types; `acceptedFileExtensions`
     * is only a browser hint and isn't enforced.
     *
     * @param {File} file
     * @returns Whether the upload file's type is in the whitelist (`allowedMIMETypes`).
     */
    validFileType(file) {
        if (this.props.allowedMIMETypes) {
            const allowed = this.props.allowedMIMETypes
                .split(",")
                .map((type) => type.trim())
                .filter(Boolean);
            // Exact match against the whitelist; an empty `file.type` (MIME
            // undetected) is rejected rather than slipping through.
            if (!file.type || !allowed.includes(file.type)) {
                this.notification.add(
                    _t(
                        `Oops! '%(fileName)s' didn’t upload since its format isn’t allowed.`,
                        {
                            fileName: file.name,
                        },
                    ),
                    {
                        type: "danger",
                    },
                );
                return false;
            }
        }
        return true;
    }

    async onSelectFileButtonClick(ev) {
        if (this.props.onClick) {
            const ok = await this.props.onClick(ev);
            if (ok !== undefined && !ok) {
                return;
            }
        }
        this.fileInputRef.el.click();
    }
}
