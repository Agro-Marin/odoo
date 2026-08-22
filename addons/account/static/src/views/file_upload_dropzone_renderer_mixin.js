/** @odoo-module native */
import {
    PASTEABLE_MIMETYPES,
    sendFilesToUploadInput,
} from "@account/components/document_file_uploader/upload_input";
import { UploadDropZone } from "@account/components/upload_drop_zone/upload_drop_zone";
import { useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * Adds paste-to-upload and drag-dropzone behaviour to the file-upload list and
 * kanban renderers.
 *
 * @param {typeof import("@odoo/owl").Component} Base list/kanban renderer to extend.
 */
export const FileUploadDropzoneRendererMixin = (Base) =>
    class extends Base {
        static components = {
            ...Base.components,
            UploadDropZone,
        };

        setup() {
            super.setup();
            this.dropzoneState = useState({ visible: false });
            this.notification = useService("notification");
            this.dropZoneTitle = _t(
                "Drop and let the AI process your bills automatically.",
            );
        }

        async onPaste(ev) {
            if (!ev.clipboardData?.items) {
                return;
            }
            ev.preventDefault();
            sendFilesToUploadInput(ev.clipboardData, {
                acceptedMimetypes: PASTEABLE_MIMETYPES,
                notification: this.notification,
            });
        }

        onDragStart(ev) {
            if (ev.dataTransfer.types.includes("Files")) {
                this.dropzoneState.visible = true;
            }
        }
    };
