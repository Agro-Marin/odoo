/** @odoo-module native */
import { MailAttachmentDropzone } from "@mail/core/common/mail_attachment_dropzone";
import { EventBus, toRaw, useEffect, useRef, useSubEnv } from "@odoo/owl";
import { useCustomDropzone } from "@web/components/dropzone";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useX2ManyCrud } from "@web/fields/relational/x2many_crud";
import { formView } from "@web/views/form";
export class MailComposerFormController extends formView.Controller {
    static props = {
        ...formView.Controller.props,
        fullComposerBus: { type: EventBus, optional: true },
    };
    static defaultProps = { fullComposerBus: new EventBus() };
    setup() {
        super.setup();
        toRaw(this.env.dialogData).model = this.props.resModel;
        useSubEnv({
            fullComposerBus: this.props.fullComposerBus,
        });
    }
}

/**
 * @param {SuggestedRecipient} recipient
 * @param {Object[]} selectedPartners
 * @returns {SuggestedRecipient}
 */
function withCorrespondingPartner(recipient, selectedPartners) {
    const partner = selectedPartners.find(
        (partner) =>
            partner.id === recipient.partner_id || partner.email === recipient.email,
    );
    if (!partner) {
        return recipient;
    }
    return {
        ...recipient,
        email: partner.email,
        lang: partner.lang,
        name: partner.name,
        partner_id: partner.id,
    };
}
export class MailComposerFormRenderer extends formView.Renderer {
    /** @returns {import("models").Thread[]} */
    _getActiveMailThreads() {
        let resIds;
        if (this.props.record.resModel === "mail.scheduled.message") {
            resIds = [this.props.record.data.res_id.resId];
        } else {
            resIds = this.props.record.data.res_ids
                ? JSON.parse(this.props.record.data.res_ids)
                : this.props.record.context.active_ids;
        }
        return resIds.map((resId) => {
            const thread = this.mailStore.Thread.insert({
                model: this.props.record.data.model,
                id: resId,
            });
            return thread;
        });
    }
    _setupReplyAllFocus() {
        useEffect(
            /**
             * @param {boolean} isInEdition
             * @param {HTMLElement|null} el
             */
            (isInEdition, el) => {
                if (
                    el &&
                    isInEdition &&
                    this.props.record.data.composition_comment_option === "reply_all"
                ) {
                    const element = el.querySelector(".note-editable[contenteditable]");
                    if (element) {
                        element.focus();
                        document.dispatchEvent(new Event("selectionchange", {}));
                    }
                }
            },
            () => [
                this.props.record.isInEdition,
                this.root.el,
                this.props.record.resId,
            ],
        );
    }
    _setupAttachmentDropzone() {
        this.attachmentUploadService = useService("mail.attachment_upload");
        this.operations = useX2ManyCrud(
            () => this.props.record.data["attachment_ids"],
            true,
        );

        useCustomDropzone(this.root, MailAttachmentDropzone, {
            /** @param {Event} event */
            onDrop: async (event) => {
                const [thread] = this._getActiveMailThreads();
                if (!thread) {
                    return;
                }
                const composer =
                    this.props.record.resModel === "mail.scheduled.message"
                        ? { attachments: [] }
                        : thread.composer;
                for (const file of event.dataTransfer.files) {
                    const attachment = await this.attachmentUploadService.upload(
                        thread,
                        composer,
                        file,
                    );
                    await this.operations.linkRecords([attachment.id]);
                }
            },
        });
    }
    /**
     * @param {import("models").Thread} thread
     * @param {Object[]} selectedPartners
     * @param {number[]} selectedPartnerIds
     */
    _updateThreadRecipients(thread, selectedPartners, selectedPartnerIds) {
        /** @param {SuggestedRecipient} recipient */
        const isSelected = (recipient) =>
            selectedPartnerIds.includes(recipient.partner_id);
        /** @param {SuggestedRecipient} recipient */
        const merged = (recipient) =>
            withCorrespondingPartner(recipient, selectedPartners);
        thread.suggestedRecipients = thread.suggestedRecipients
            .map(merged)
            .filter(isSelected);
        thread.additionalRecipients = thread.additionalRecipients
            .map(merged)
            .filter(isSelected);
        for (const partner of selectedPartners) {
            const allRecipients = [
                ...thread.suggestedRecipients,
                ...thread.additionalRecipients,
            ];
            if (
                !allRecipients.some((recipient) => recipient.partner_id === partner.id)
            ) {
                thread.additionalRecipients.push({
                    display_name: partner.display_name,
                    email: partner.email,
                    lang: partner.lang,
                    name: partner.name,
                    partner_id: partner.id,
                });
            }
        }
    }
    async _syncRecipientsFromFullComposer() {
        if (this.props.record.resModel === "mail.scheduled.message") {
            return;
        }
        const selectedPartnerIds = this.props.record.data.partner_ids.currentIds;
        const selectedPartners = await this.orm.searchRead(
            "res.partner",
            [["id", "in", selectedPartnerIds]],
            ["email", "id", "lang", "name"],
        );
        for (const thread of this._getActiveMailThreads()) {
            this._updateThreadRecipients(thread, selectedPartners, selectedPartnerIds);
        }
    }
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.root = useRef("compiled_view_root");
        this._setupReplyAllFocus();
        this._setupAttachmentDropzone();
        this.env.dialogData.dismiss = () => this._syncRecipientsFromFullComposer();
    }
}

registry.category("views").add("mail_composer_form", {
    ...formView,
    Controller: MailComposerFormController,
    Renderer: MailComposerFormRenderer,
});
