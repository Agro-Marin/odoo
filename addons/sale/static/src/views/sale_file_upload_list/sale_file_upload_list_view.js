/** @odoo-module native */
import { fileUploadListView } from "@account/views/file_upload_list/file_upload_list_view";
import { registry } from "@web/core/registry";

import { SaleFileUploadListController } from "./sale_file_upload_list_controller.js";
import { SaleFileUploadListRenderer } from "./sale_file_upload_list_renderer.js";

export const saleFileUploadListView = {
    ...fileUploadListView,
    Controller: SaleFileUploadListController,
    Renderer: SaleFileUploadListRenderer,
};

registry.category("views").add("sale_file_upload_list", saleFileUploadListView);
