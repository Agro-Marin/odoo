/** @odoo-module native */
import { FileUploadKanbanController } from '@account/views/file_upload_kanban/file_upload_kanban_controller';
import { saleFileUploadController } from '../sale_file_upload_mixins.js';

export const SaleFileUploadKanbanController = saleFileUploadController(FileUploadKanbanController);
