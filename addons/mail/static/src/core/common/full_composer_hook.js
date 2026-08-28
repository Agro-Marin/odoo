/** @odoo-module native */
import { saveComposerDraft } from "@mail/core/common/composer_draft";
import { EventBus, toRaw, useComponent, useState } from "@odoo/owl";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { isHtmlEmpty } from "@web/core/utils/dom/html";

/**
 * @returns {{ bus: EventBus, isOpen: boolean, open: () => Promise<void>, saveContent: () => void, }}
 */
/**
 * @param {import("@odoo/owl").Component} comp
 * @returns {Promise<any[]>}
 */
async function resolveFullComposerRecipients(comp) {
    const allRecipients = [...comp.thread.suggestedRecipients];
    if (comp.props.type === "note") {
        return allRecipients;
    }
    allRecipients.push(...comp.thread.additionalRecipients);
    const newPartners = allRecipients.filter((recipient) => !recipient.partner_id);
    if (newPartners.length === 0) {
        return allRecipients;
    }
    const partners = await rpc("/mail/partner/from_email", {
        thread_model: comp.thread.model,
        thread_id: comp.thread.id,
        emails: newPartners.map((recipient) => recipient.email),
    });
    for (const partnerData of partners) {
        const partner = comp.store["res.partner"].insert(partnerData);
        const sourceEmail = partnerData.source_email ?? partnerData.email;
        const recipient = allRecipients.find(
            (recipient) => recipient.email === sourceEmail,
        );
        if (recipient) {
            recipient.partner_id = partner.id;
        }
    }
    return allRecipients;
}
/**
 * @param {import("@odoo/owl").Component} comp
 * @returns {string}
 */
function getFullComposerBody(comp) {
    const default_body = comp.props.composer.composerHtml;
    if (isHtmlEmpty(default_body)) {
        toRaw(comp.props.composer).emailAddSignature = true;
    }
    const signature = comp.thread.effectiveSelf.main_user_id?.getSignatureBlock();
    return comp.formatDefaultBodyForFullComposer(
        default_body,
        comp.props.composer.emailAddSignature ? signature : "",
    );
}
/**
 * @param {import("@odoo/owl").Component} comp
 * @param {any[]} allRecipients
 * @param {string} default_body
 * @returns {Object}
 */
function getFullComposerContext(comp, allRecipients, default_body) {
    return {
        default_attachment_ids: comp.props.composer.attachments.map(
            (attachment) => attachment.id,
        ),
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
        is_thread_composer: true,
        ...comp.fullComposerAdditionalContext,
    };
}
export function useFullComposer() {
    const comp = useComponent();
    const state = useState({ isOpen: false });
    let bus = new EventBus();
    /**
     * @param {Object} [args]
     * @param {boolean} [args.dismiss]
     * @param {boolean} [args.special]
     */
    function onFullComposerClose(args) {
        const accidentalDiscard = args?.dismiss;
        const isDiscard = accidentalDiscard || args?.special;
        if (accidentalDiscard) {
            bus.trigger("ACCIDENTAL_DISCARD", {
                /** @param {boolean} isEmpty */
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
        bus = new EventBus();
    }
    return {
        get bus() {
            return bus;
        },
        get isOpen() {
            return state.isOpen;
        },
        saveContent() {
            bus.trigger("SAVE_CONTENT", {
                /** @param {Object} content */
                onSaveContent: (content) =>
                    saveComposerDraft(toRaw(comp.props.composer), {
                        ...content,
                        fromFullComposer: true,
                    }),
            });
        },
        async open() {
            comp.props.composer.restoredFromFullComposer = false;
            const allRecipients = await resolveFullComposerRecipients(comp);
            const context = getFullComposerContext(
                comp,
                allRecipients,
                getFullComposerBody(comp),
            );
            const action = {
                name: comp.props.type === "note" ? _t("Log note") : _t("Compose Email"),
                type: "ir.actions.act_window",
                res_model: "mail.compose.message",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context,
            };
            await comp.env.services.action.doAction(action, {
                onClose: onFullComposerClose,
                props: { fullComposerBus: bus },
            });
            state.isOpen = true;
        },
    };
}
