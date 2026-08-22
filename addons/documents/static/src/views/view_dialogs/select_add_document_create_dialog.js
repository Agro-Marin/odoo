/** @odoo-module native */
import { _t } from "@web/core/translation";
import { omit } from "@web/core/utils/collections/objects";

import { useService } from "@web/core/utils/hooks";
import { SelectCreateDialog } from "@web/views/view_dialogs";

export class SelectAddDocumentCreateDialog extends SelectCreateDialog {
    static template = "documents.SelectAddDocumentCreateDialog";
    static props = {
        ...SelectCreateDialog.props,
        chatterParams: { type: Object },
        resModel: { type: String },
        title: { type: String },
        domain: { type: Array, optional: true },
        context: { type: Object, optional: true },
    };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.store = useService("mail.store");
        this.notification = useService("notification");

        const { thread = {}, model, resId } = this.props.chatterParams || this.props;
        this.model = thread.model ?? model;
        this.resId = thread.id ?? resId;
    }

    get viewProps() {
        const baseProps = super.viewProps;
        return {
            ...omit(baseProps, "forceGlobalClick", "display"),
            type: "list",
            allowSelectors: true,
        };
    }

    get addDocumentsAttachmentMethod() {
        return this.props.chatterParams?.addDocumentsAttachment || this.addDocumentsAttachment;
    }

    get pasteDocumentsLinkMethod() {
        return this.props.chatterParams?.pasteDocumentsLink || this.pasteDocumentsLink;
    }

    get isPlugin() {
        return this.props.chatterParams?.isPlugin;
    }

    get isNewRecord() {
        return this.props.chatterParams?.isNewRecord;
    }

    /**
     * @param {Array} resIds
     */
    async pasteDocumentsLink(resIds) {
        let response;
        try {
            response = await this.orm.read("documents.document", resIds, [
                "display_name",
                "access_url",
            ]);
        } catch (error) {
            this.notification.add(
                _t("Failed to paste link(s): ") + (error.data?.message || error.toString()),
                { type: "danger" }
            );
            this.props.close();
            return;
        }
        if (this.props.chatterParams.isFromFullComposer) {
            this.props.chatterParams.addDocumentsBus.trigger("PASTE_SHARE_LINKS", {
                links: response,
            });
        } else {
            this.addToThread(this.model, this.resId);
            const shareLinks = response
                .map(({ display_name, access_url }) => `${display_name}: ${access_url}`)
                .join("\n");
            this.props.chatterParams.composer.composerText += `\n${shareLinks}`;
        }
        this.notification.add(_t("Link(s) pasted!"), { type: "success" });
        this.props.close();
    }

    /**
     * @param {Array} resIds
     */
    async addDocumentsAttachment(resIds) {
        let processedAttachments;
        try {
            const attachmentRecords = await this.orm.call(
                "documents.document",
                "add_documents_attachment",
                [resIds, "mail.compose.message", 0]
            );
            processedAttachments = await this._processAttachments(attachmentRecords);
        } catch (error) {
            this.notification.add(
                _t("Failed to add document(s): ") + (error.data?.message || error.toString()),
                { type: "danger" }
            );
            this.props.close();
            return;
        }
        const thread = this.props.chatterParams?.thread || this.addToThread(this.model, this.resId);
        const composer = this.props.chatterParams?.composer || thread.composer;

        const attachmentIds = [];
        for (const { name, ...attachmentRecord } of processedAttachments) {
            const extension = name.slice(Math.max(0, name.lastIndexOf(".") + 1));
            composer.attachments.push({ name, extension, ...attachmentRecord });
            attachmentIds.push(attachmentRecord.id);
        }
        this.props.chatterParams.saveRecordHandler?.(attachmentIds);
        this.props.close();
    }

    async _processAttachments(attachmentRecords) {
        return attachmentRecords;
    }

    /**
     * @param {String} currentModel
     * @param {Number} currentChatterRecordId
     */
    addToThread(currentModel, currentChatterRecordId) {
        return this.store.Thread.insert({
            model: currentModel,
            id: currentChatterRecordId,
        });
    }
}
