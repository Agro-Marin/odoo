/** @odoo-module native */
import { UploadDropZone } from "@account/components/upload_drop_zone/upload_drop_zone";
import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

import { uploadFileFromData } from "./upload_file_from_data_hook.js";

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
            this.uploadFileFromData = uploadFileFromData(useService("notification"));
            this.dropZoneTitle = _t(
                "Drop and let the AI process your bills automatically.",
            );
        }

        async onPaste(ev) {
            if (!ev.clipboardData?.items) {
                return;
            }
            ev.preventDefault();
            await this.uploadFileFromData(ev.clipboardData);
        }

        onDragStart(ev) {
            if (ev.dataTransfer.types.includes("Files")) {
                this.dropzoneState.visible = true;
            }
        }
    };
