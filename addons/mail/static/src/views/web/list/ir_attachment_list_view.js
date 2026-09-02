/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list";

import { IrAttachmentListController } from "./ir_attachment_list_controller.js";

export const irAttachmentListView = {
    ...listView,
    Controller: IrAttachmentListController,
};

registry.category("views").add("ir_attachment_list", irAttachmentListView);
