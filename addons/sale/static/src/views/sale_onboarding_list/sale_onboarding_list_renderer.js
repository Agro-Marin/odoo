/** @odoo-module native */
import { SaleFileUploadListRenderer } from '../sale_file_upload_list/sale_file_upload_list_renderer.js';
import { saleOnboardingRenderer } from '../sale_file_upload_mixins.js';

export const SaleListRenderer = saleOnboardingRenderer(
    SaleFileUploadListRenderer,
    "sale.SaleListRenderer",
);
