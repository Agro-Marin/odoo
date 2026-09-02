/** @odoo-module native */
import { useFileViewer } from "@web/components/file_viewer";
import { useService } from "@web/core/utils/hooks";
import { CANCEL_GLOBAL_CLICK, KanbanRecord } from "@web/views/kanban";

export class ProductDocumentKanbanRecord extends KanbanRecord {
    setup() {
        super.setup();
        this.store = useService("mail.store");
        this.fileViewer = useFileViewer();
    }

    /**
     * The ir.attachment holding the file, or a falsy value for a record that
     * has none (a document pointing at a URL).
     *
     * The view is reused by models that name that relation differently, so a
     * subclass points this at its own field.
     */
    get attachment() {
        return this.props.record.data.attachment_id;
    }

    /**
     * @override
     *
     * Override to open the preview upon clicking the image, if compatible.
     */
    onGlobalClick(ev) {
        if (ev.target.closest(CANCEL_GLOBAL_CLICK)) {
            return;
        } else if (this.attachment && ev.target.closest(".o_kanban_previewer")) {
            const attachment = this.store["ir.attachment"].insert({
                id: this.attachment.id,
                name: this.props.record.data.name,
                mimetype: this.props.record.data.mimetype,
            });
            this.fileViewer.open(attachment);
            return;
        }
        return super.onGlobalClick(...arguments);
    }
}
