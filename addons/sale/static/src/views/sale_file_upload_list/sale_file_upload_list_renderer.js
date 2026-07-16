/** @odoo-module native */
import { FileUploadListRenderer } from "@account/views/file_upload_list/file_upload_list_renderer";

import { saleFileUploadRenderer } from "../sale_file_upload_mixins.js";

export const SaleFileUploadListRenderer =
    saleFileUploadRenderer(FileUploadListRenderer);
