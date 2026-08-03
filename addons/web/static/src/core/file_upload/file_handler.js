// @ts-check
/** @odoo-module native */

/** @module @web/core/file_upload/file_handler */

import { Component, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
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
        // Boolean, or a per-file predicate `(file) => boolean`. A caller that
        // routes SOME files past the server (cloud storage) must be able to
        // exempt those without disabling the size warning for the rest.
        checkSize: { type: [Boolean, Function], optional: true },
        inputName: { type: String, optional: true },
        fileUploadClass: { type: String, optional: true },
        acceptedFileExtensions: { type: String, optional: true },
        slots: { type: Object, optional: true },
        showUploadingText: { type: Boolean, optional: true },
        allowedMIMETypes: { type: String, optional: true },
        createObjectUrl: { type: Boolean, optional: true },
    };
    static defaultProps = {
        checkSize: true,
        showUploadingText: true,
        createObjectUrl: false,
    };

    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {{ el: HTMLInputElement | null }} */
    fileInputRef;
    /** @type {{ isUploading: boolean }} */
    state;

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
        const files = [...(inputEl.files ?? [])].filter((file) =>
            this.validFileType(file),
        );
        if (!files.length) {
            inputEl.value = "";
            return;
        }
        try {
            for (const file of files) {
                const checkSize =
                    typeof this.props.checkSize === "function"
                        ? this.props.checkSize(file)
                        : this.props.checkSize;
                if (checkSize && !checkFileSize(file.size, this.notification)) {
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
            inputEl.value = "";
        }
        if (this.props.multiUpload && this.props.onUploadComplete) {
            this.props.onUploadComplete({});
        }
    }

    /**
     * @param {File} file
     */
    validFileType(file) {
        if (this.props.allowedMIMETypes) {
            const allowed = this.props.allowedMIMETypes
                .split(",")
                .map((/** @type {string} */ type) => type.trim())
                .filter(Boolean);
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

    /** @param {MouseEvent} ev */
    async onSelectFileButtonClick(ev) {
        if (this.props.onClick) {
            const ok = await this.props.onClick(ev);
            if (ok !== undefined && !ok) {
                return;
            }
        }
        this.fileInputRef.el?.click();
    }
}
