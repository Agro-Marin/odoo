/** @odoo-module native */
import { attachmentDownloadMenuItem } from "@mail/views/web/attachment/attachment_download";
import { ListController } from "@web/views/list";

export class IrAttachmentListController extends ListController {
    getStaticActionMenuItems() {
        return {
            ...super.getStaticActionMenuItems(),
            downloadAttachments: attachmentDownloadMenuItem(this),
        };
    }
}
