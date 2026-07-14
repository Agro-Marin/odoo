/** @odoo-module native */
import { saveComposerDraft } from "@mail/core/common/composer_draft";
import { EventBus, toRaw, useComponent, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { isHtmlEmpty } from "@web/core/utils/dom/html";

/**
 * Orchestrates the full-composer (`mail.compose.message`) dialog of a
 * Composer component: recipient resolution, opening the dialog action, and
 * the EventBus handshake used to save/recover the dialog's content when it
 * closes (accidental discard vs. explicit discard/save-and-close).
 *
 * Every extension point stays on the component and is called back late-bound
 * (`formatDefaultBodyForFullComposer`, `fullComposerAdditionalContext`,
 * `clear`, `saveContent`, `restoreContent`, `onCloseFullComposerCallback`),
 * so downstream patches/overrides of those members keep applying.
 *
 * @returns {{
 *  bus: EventBus,
 *  isOpen: boolean,
 *  open: () => Promise<void>,
 *  saveContent: () => void,
 * }}
 */
export function useFullComposer() {
    const comp = useComponent();
    const state = useState({ isOpen: false });
    let bus = new EventBus();
    return {
        /** Bus shared with the currently opened full composer form (if any). */
        get bus() {
            return bus;
        },
        /** Whether the full composer dialog is currently open. */
        get isOpen() {
            return state.isOpen;
        },
        /**
         * Asks the opened full composer form (through the bus handshake) for
         * its current content and persists it as a draft coming from the
         * full composer.
         */
        saveContent() {
            bus.trigger("SAVE_CONTENT", {
                onSaveContent: (content) =>
                    saveComposerDraft(toRaw(comp.props.composer), {
                        ...content,
                        fromFullComposer: true,
                    }),
            });
        },
        async open() {
            comp.props.composer.restoredFromFullComposer = false;
            const allRecipients = [...comp.thread.suggestedRecipients];
            if (comp.props.type !== "note") {
                allRecipients.push(...comp.thread.additionalRecipients);
                // auto-create partners:
                const newPartners = allRecipients.filter(
                    (recipient) => !recipient.partner_id,
                );
                if (newPartners.length !== 0) {
                    const recipientEmails = [];
                    newPartners.forEach((recipient) => {
                        recipientEmails.push(recipient.email);
                    });
                    const partners = await rpc("/mail/partner/from_email", {
                        thread_model: comp.thread.model,
                        thread_id: comp.thread.id,
                        emails: recipientEmails,
                    });
                    for (const index in partners) {
                        const partnerData = partners[index];
                        const partner = comp.store["res.partner"].insert(partnerData);
                        const email = recipientEmails[index];
                        const recipient = allRecipients.find(
                            (recipient) => recipient.email === email,
                        );
                        recipient.partner_id = partner.id;
                    }
                }
            }
            const attachmentIds = comp.props.composer.attachments.map(
                (attachment) => attachment.id,
            );
            let default_body = comp.props.composer.composerHtml;
            if (isHtmlEmpty(default_body)) {
                const composer = toRaw(comp.props.composer);
                // Reset signature when recovering an empty body.
                composer.emailAddSignature = true;
            }
            const signature =
                comp.thread.effectiveSelf.main_user_id?.getSignatureBlock();
            default_body = comp.formatDefaultBodyForFullComposer(
                default_body,
                comp.props.composer.emailAddSignature ? signature : "",
            );
            const context = {
                default_attachment_ids: attachmentIds,
                default_body,
                default_email_add_signature: false,
                default_model: comp.thread.model,
                default_partner_ids:
                    comp.props.type === "note"
                        ? []
                        : allRecipients
                              .filter((recipient) => recipient.partner_id)
                              .map((recipient) => recipient.partner_id),
                default_res_ids: [comp.thread.id],
                default_subtype_xmlid:
                    comp.props.type === "note" ? "mail.mt_note" : "mail.mt_comment",
                clicked_on_full_composer: true,
                body_contains_signature_only:
                    !comp.props.composer.composerText ||
                    comp.props.composer.composerText.trim().length === 0,
                // Changed in 18.2+: finally get rid of autofollow, following should be done manually
                is_thread_composer: true,
                ...comp.fullComposerAdditionalContext,
            };
            const action = {
                name: comp.props.type === "note" ? _t("Log note") : _t("Compose Email"),
                type: "ir.actions.act_window",
                res_model: "mail.compose.message",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: context,
            };
            const options = {
                onClose: (args) => {
                    // args === { dismiss: true } : click on 'X' or press escape
                    // args === { special: true } : click on 'discard'
                    const accidentalDiscard = args?.dismiss;
                    const isDiscard = accidentalDiscard || args?.special;
                    if (accidentalDiscard) {
                        bus.trigger("ACCIDENTAL_DISCARD", {
                            onAccidentalDiscard: (isEmpty) => {
                                if (!isEmpty) {
                                    state.isOpen = true;
                                    comp.saveContent();
                                    comp.restoreContent();
                                    state.isOpen = false;
                                }
                            },
                        });
                    } else {
                        comp.clear();
                    }
                    comp.props.composer.replyToMessage = undefined;
                    comp.onCloseFullComposerCallback(isDiscard);
                    state.isOpen = false;
                    // Use another event bus so that no message is sent to the
                    // closed composer.
                    bus = new EventBus();
                },
                props: {
                    fullComposerBus: bus,
                },
            };
            await comp.env.services.action.doAction(action, options);
            state.isOpen = true;
        },
    };
}
