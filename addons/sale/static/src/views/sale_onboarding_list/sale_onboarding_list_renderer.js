/** @odoo-module native */
import { SaleFileUploadListRenderer } from '../sale_file_upload_list/sale_file_upload_list_renderer.js';
import { SaleActionHelper } from "../../js/sale_action_helper/sale_action_helper.js";

export class SaleListRenderer extends SaleFileUploadListRenderer {
    static template = "sale.SaleListRenderer";
    static components = {
        ...SaleFileUploadListRenderer.components,
        SaleActionHelper,
    };
};
