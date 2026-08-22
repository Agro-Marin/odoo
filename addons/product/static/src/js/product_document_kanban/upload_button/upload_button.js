/** @odoo-module native */
import { Component, useRef } from "@odoo/owl";
import { checkFileType } from "@web/core/utils/files";
import { useBus, useService } from "@web/core/utils/hooks";

export class UploadButton extends Component {
    static template = "product.UploadButton";
    static props = {
        formData: { type: Object, optional: true },
        // See https://www.iana.org/assignments/media-types/media-types.xhtml
        allowedMIMETypes: { type: String, optional: true },
        load: Function,
        uploadRoute: String,
    };
    static defaultProps = {
        formData: {},
    };

    setup() {
        this.uploadFileInputRef = useRef("uploadFileInput");
        this.fileUploadService = useService("file_upload");
        this.notification = useService("notification");
        // The file_upload bus is application-wide: it fires for every upload in
        // the session, a chatter attachment elsewhere included. Reload only for
        // the uploads this button started, identified by the FormData instance
        // it filled in -- `buildFormData` runs before the request is sent, so
        // the entry is always registered before the event can fire, and nothing
        // is added to the payload (not every upload route takes **kwargs).
        this.ownUploads = new Set();
        useBus(this.fileUploadService.bus, "FILE_UPLOAD_LOADED", async (ev) => {
            if (!this.ownUploads.delete(ev.detail.upload?.data)) {
                return;
            }
            await this.props.load();
        });
        useBus(this.fileUploadService.bus, "FILE_UPLOAD_ERROR", (ev) => {
            this.ownUploads.delete(ev.detail.upload?.data);
        });
    }

    async onFileInputChange(ev) {
        const input = ev.target;
        try {
            const files = [...input.files].filter((file) => this.validFileType(file));
            if (!files.length) {
                return;
            }
            await this.fileUploadService.upload(this.props.uploadRoute, files, {
                buildFormData: (formData) => this.buildFormData(formData),
            });
        } finally {
            // Reset the value so the same file may be selected twice -- also
            // after a rejected upload, which otherwise looks like a dead button.
            input.value = "";
        }
    }

    /**
     * The `allowedMIMETypes` prop can restrict the file types users are guided to select.
     * However, the `accept` attribute doesn't enforce strict validation; it only suggests
     * file types for browsers, so the selection is checked here as well.
     *
     * @param {File} file
     * @returns Whether the upload file's type is in the whitelist (`allowedMIMETypes`).
     */
    validFileType(file) {
        return checkFileType(file, this.props.allowedMIMETypes, this.notification);
    }

    buildFormData(formData) {
        this.ownUploads.add(formData);
        for (const [key, value] of Object.entries(this.props.formData)) {
            formData.append(key, value);
        }
    }
}
