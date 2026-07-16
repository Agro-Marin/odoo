/** @odoo-module native */
import { FileUploadListController } from "@account/views/file_upload_list/file_upload_list_controller";

import { saleFileUploadController } from "../sale_file_upload_mixins.js";

export const SaleFileUploadListController = saleFileUploadController(
    FileUploadListController,
);
