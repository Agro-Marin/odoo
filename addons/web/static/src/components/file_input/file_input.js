// @ts-check
/** @odoo-module native */

import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { useFileUploader } from "@web/core/utils/files";
/**
 * @typedef FileInputProps
 * @property {string} [acceptedFileExtensions="*"]
 * @property {boolean} [autoOpen]
 * @property {boolean} [hidden]
 * @property {boolean} [multiUpload=false]
 * @property {(data: any, files: FileList | File[]) => any} [onUpload]
 * @property {(files: File[]) => any} [onWillUploadFiles]
 * @property {() => Promise<boolean>} [beforeOpen]
 * @property {number} [resId]
 * @property {string} [resModel]
 * @property {string} [route="/web/binary/upload_attachment"]
 */

/** @extends {Component<FileInputProps>} */
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

    /** @type {ReturnType<typeof useFileUploader>} */
    uploadFiles;
    /** @type {import("@odoo/owl").Ref<HTMLInputElement>} */
    fileInputRef;
    /** @type {{ isDisable: boolean }} */
    state;

    setup() {
        this.uploadFiles = useFileUploader();
        this.fileInputRef = /** @type {any} */ (useRef("file-input"));
        this.state = useState({
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
        /** @type {Record<string, any>} */
        const params = {
            csrf_token: odoo.csrf_token,
            ufile: [...(this.fileInputRef.el?.files ?? [])],
        };
        if (resModel) {
            params.model = resModel;
        }
        if (resId !== undefined) {
            params.id = resId;
        }
        return params;
    }

    async onFileInputChange() {
        this.state.isDisable = true;
        const httpParams = this.httpParams;
        try {
            if (this.props.onWillUploadFiles) {
                httpParams.ufile = await this.props.onWillUploadFiles(httpParams.ufile);
            }
            const parsedFileData = await this.uploadFiles(this.props.route, httpParams);
            if (parsedFileData) {
                this.props.onUpload(parsedFileData, this.fileInputRef.el?.files ?? []);
            }
        } finally {
            if (this.fileInputRef.el) {
                this.fileInputRef.el.value = "";
            }
            this.state.isDisable = false;
        }
    }

    async onTriggerClicked() {
        if (await this.props.beforeOpen()) {
            this.fileInputRef.el?.click();
        }
    }
}
