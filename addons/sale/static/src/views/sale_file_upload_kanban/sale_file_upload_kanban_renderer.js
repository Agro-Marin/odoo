/** @odoo-module native */
import { FileUploadKanbanRenderer } from "@account/views/file_upload_kanban/file_upload_kanban_renderer";

import { saleFileUploadRenderer } from "../sale_file_upload_mixins.js";

export const SaleFileUploadKanbanRenderer = saleFileUploadRenderer(
    FileUploadKanbanRenderer,
);
