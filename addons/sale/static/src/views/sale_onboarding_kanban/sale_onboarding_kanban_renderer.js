/** @odoo-module native */
import { SaleFileUploadKanbanRenderer } from "../sale_file_upload_kanban/sale_file_upload_kanban_renderer.js";
import { saleOnboardingRenderer } from "../sale_file_upload_mixins.js";

export const SaleKanbanRenderer = saleOnboardingRenderer(
    SaleFileUploadKanbanRenderer,
    "sale.SaleKanbanRenderer",
);
