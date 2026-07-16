/** @odoo-module native */
import { ListRenderer } from "@web/views/list/list_renderer";

import { FileUploadDropzoneRendererMixin } from "../file_upload_dropzone_renderer_mixin.js";

export class FileUploadListRenderer extends FileUploadDropzoneRendererMixin(
    ListRenderer,
) {
    static template = "account.FileUploadListRenderer";
}
