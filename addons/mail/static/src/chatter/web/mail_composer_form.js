/** @odoo-module native */
import { MailAttachmentDropzone } from "@mail/core/common/mail_attachment_dropzone";
import { EventBus, toRaw, useEffect, useRef, useSubEnv } from "@odoo/owl";
import { useCustomDropzone } from "@web/components/dropzone/dropzone_hook";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useX2ManyCrud } from "@web/fields/relational/x2many_crud";
import { formView } from "@web/views/form/form_view";
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

export class MailComposerFormRenderer extends formView.Renderer {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.root = useRef("compiled_view_root");
        useEffect(
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

        const getActiveMailThreads = () => {
            let resIds;
            if (this.props.record.resModel === "mail.scheduled.message") {
                resIds = [this.props.record.data.res_id.resId];
            } else {
                // composer does not store res_ids past a certain limit, assume active_ids is used
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
        };

        this.attachmentUploadService = useService("mail.attachment_upload");
        this.operations = useX2ManyCrud(
            () => this.props.record.data["attachment_ids"],
            true,
        );

        useCustomDropzone(this.root, MailAttachmentDropzone, {
            /** @param {Event} event */
            onDrop: async (event) => {
                // Upload each dropped file exactly ONCE and link it to the single
                // composer wizard: the composer is one `mail.compose.message`
                // record regardless of how many recipients it targets, so looping
                // over the threads would attach N copies of every file.
                const [thread] = getActiveMailThreads();
                if (!thread) {
                    return;
                }
                // Use an isolated composer object instead of thread.composer to
                // avoid pushing into the main thread's composer.attachments list,
                // which is observed by the chatter.
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

        /** @param {function} callback */
        const onCloseWizardModal = (callback) => {
            this.env.dialogData.dismiss = callback;
        };

        onCloseWizardModal(async () => {
            if (this.props.record.resModel === "mail.scheduled.message") {
                return;
            }

            const selectedPartnerIds = this.props.record.data.partner_ids.currentIds;
            const selectedPartners = await this.orm.searchRead(
                "res.partner",
                [["id", "in", selectedPartnerIds]],
                ["email", "id", "lang", "name"],
            );

            /**
             * @param {SuggestedRecipient} recipient
             * @returns {SuggestedRecipient}
             */
            const updateRecipientWithCorrespondingPartner = (recipient) => {
                const partner = selectedPartners.find(
                    (partner) =>
                        partner.id === recipient.partner_id ||
                        partner.email === recipient.email,
                );
                if (partner) {
                    return {
                        ...recipient,
                        email: partner.email,
                        lang: partner.lang,
                        name: partner.name,
                        partner_id: partner.id,
                    };
                }
                return recipient;
            };

            /**
             * @param {SuggestedRecipient} recipient
             * @returns {boolean}
             */
            const isRecipientSelectedFromFullMailComposer = (recipient) =>
                selectedPartnerIds.includes(recipient.partner_id);

            for (const thread of getActiveMailThreads()) {
                thread.suggestedRecipients = thread.suggestedRecipients.map(
                    updateRecipientWithCorrespondingPartner,
                );
                thread.additionalRecipients = thread.additionalRecipients.map(
                    updateRecipientWithCorrespondingPartner,
                );

                thread.suggestedRecipients = thread.suggestedRecipients.filter(
                    isRecipientSelectedFromFullMailComposer,
                );
                thread.additionalRecipients = thread.additionalRecipients.filter(
                    isRecipientSelectedFromFullMailComposer,
                );

                for (const partner of selectedPartners) {
                    const allRecipients = [
                        ...thread.suggestedRecipients,
                        ...thread.additionalRecipients,
                    ];
                    if (
                        !allRecipients.some(
                            (recipient) => recipient.partner_id === partner.id,
                        )
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
        });
    }
}

registry.category("views").add("mail_composer_form", {
    ...formView,
    Controller: MailComposerFormController,
    Renderer: MailComposerFormRenderer,
});
