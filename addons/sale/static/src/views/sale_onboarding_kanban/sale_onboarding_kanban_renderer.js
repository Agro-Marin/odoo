/** @odoo-module native */
import { SaleFileUploadKanbanRenderer } from '../sale_file_upload_kanban/sale_file_upload_kanban_renderer.js';
import { SaleActionHelper } from "../../js/sale_action_helper/sale_action_helper.js";

export class SaleKanbanRenderer extends SaleFileUploadKanbanRenderer {
    static template = "sale.SaleKanbanRenderer";
    static components = {
        ...SaleFileUploadKanbanRenderer.components,
        SaleActionHelper,
    };
};
