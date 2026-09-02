/** @odoo-module native */
import { attachmentDownloadMenuItem } from "@mail/views/web/attachment/attachment_download";
import { KanbanController } from "@web/views/kanban";

export class IrAttachmentKanbanController extends KanbanController {
    getStaticActionMenuItems() {
        return {
            ...super.getStaticActionMenuItems(),
            downloadAttachments: attachmentDownloadMenuItem(this),
        };
    }
}
