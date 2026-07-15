/** @odoo-module native */
import { generateEmojisOnHtml } from "@mail/utils/common/format";
import { createDocumentFragmentFromContent, isMarkup } from "@web/core/utils/dom/html";
import { renderToElement } from "@web/core/utils/render";

/**
 * Message-posting helpers extracted from the store service: mention detection
 * from composed text and assembly of the `/mail/message/post` parameters.
 * Kept as free functions taking the store explicitly so they can be unit
 * tested without standing up the whole store, and so the store service is not
 * the home of every message concern.
 */

/**
 * Rewrite in place the `#channel` mention anchors of a rendered message body to
 * carry the channel/thread icon. Pure DOM transform — no store needed.
 *
 * @param {HTMLAnchorElement[]} channelLinks
 */
export function handleValidChannelMention(channelLinks) {
    for (const linkEl of channelLinks.filter(
        (el) => !el.querySelector(".fa-comments-o, .fa-hashtag"),
    )) {
        const text = linkEl.textContent.substring(1); // remove '#' prefix
        const icon = linkEl.classList.contains("o_channel_redirect_asThread")
            ? "fa-regular fa-comments"
            : "fa-solid fa-hashtag";
        const iconEl = renderToElement("mail.Message.mentionedChannelIcon", { icon });
        linkEl.replaceChildren(iconEl);
        linkEl.insertAdjacentText("beforeend", ` ${text}`);
    }
}

/**
 * Fill `postData.partner_ids_mention_token` from the mention tokens of the
 * partners already listed in `postData.partner_ids`.
 *
 * @param {import("models").Store} store
 * @param {Object} postData
 */
export function fillPartnersMentionToken(store, postData) {
    postData.partner_ids_mention_token ||= {};
    for (const pid of postData.partner_ids) {
        const partner = store["res.partner"].get(pid);
        if (partner?.mention_token) {
            postData.partner_ids_mention_token[pid] = partner.mention_token;
        }
    }
}

/**
 * From a composed `body`, keep only the mentions (threads, partners, roles,
 * special mentions) whose textual form actually appears in it.
 *
 * @param {import("models").Store} store
 * @param {string|ReturnType<import("@odoo/owl").markup>} body
 * @param {Object} [options]
 */
export function getMentionsFromText(
    store,
    body,
    {
        mentionedChannels = [],
        mentionedPartners = [],
        mentionedRoles = [],
        thread,
    } = {},
) {
    const validMentions = {};
    const segments = isMarkup(body)
        ? Array.from(
              createDocumentFragmentFromContent(body).querySelectorAll("a"),
              (a) => a.textContent,
          )
        : [body];
    validMentions.threads = mentionedChannels.filter((thread) => {
        const mention = thread.parent_channel_id
            ? `#${thread.parent_channel_id.displayName} > ${thread.displayName}`
            : `#${thread.displayName}`;
        return segments.some((segment) => segment.includes(mention));
    });
    validMentions.partners = mentionedPartners.filter((partner) =>
        segments.some((segment) =>
            segment.includes(`@${thread?.getPersonaName?.(partner) ?? partner.name}`),
        ),
    );
    validMentions.roles = mentionedRoles.filter((role) =>
        segments.some((segment) => segment.includes(`@${role.name}`)),
    );
    validMentions.specialMentions = store.specialMentions
        .filter((special) =>
            segments.some((segment) => segment.includes(`@${special.label}`)),
        )
        .map((special) => special.label);
    return validMentions;
}

/**
 * Assemble the parameters for the `/mail/message/post` route from the composer
 * `postData` and the target `thread`.
 *
 * @param {import("models").Store} store
 * @param {Object} param1
 */
export async function getMessagePostParams(store, { body, postData, thread }) {
    const {
        attachments,
        cannedResponseIds,
        emailAddSignature,
        isNote,
        mentionedChannels,
        mentionedPartners,
        mentionedRoles,
    } = postData;
    const subtype = isNote ? "mail.mt_note" : "mail.mt_comment";
    const validMentions = getMentionsFromText(store, body, {
        mentionedChannels,
        mentionedPartners,
        mentionedRoles,
        thread,
    });
    const partner_ids = validMentions?.partners.map((partner) => partner.id) ?? [];
    const role_ids = validMentions?.roles.map((role) => role.id) ?? [];
    const recipientEmails = [];
    if (!isNote) {
        const allRecipients = [
            ...thread.suggestedRecipients,
            ...thread.additionalRecipients,
        ];
        const recipientIds = allRecipients
            .filter((recipient) => recipient.persona)
            .map((recipient) => recipient.persona.id);
        allRecipients
            .filter((recipient) => !recipient.persona)
            .forEach((recipient) => {
                recipientEmails.push(recipient.email);
            });
        partner_ids.push(...recipientIds);
    }
    postData = {
        body: await generateEmojisOnHtml(body),
        email_add_signature: emailAddSignature,
        message_type: "comment",
        subtype_xmlid: subtype,
    };
    if (attachments.length) {
        postData.attachment_ids = attachments.map(({ id }) => id);
    }
    if (partner_ids.length) {
        Object.assign(postData, { partner_ids });
        fillPartnersMentionToken(store, postData);
    }
    if (role_ids.length) {
        Object.assign(postData, { role_ids });
    }
    if (thread.isChannelKind && validMentions?.specialMentions.length) {
        postData.special_mentions = validMentions.specialMentions;
    }
    if (attachments.length) {
        postData.attachment_tokens = attachments.map(
            (attachment) => attachment.ownership_token,
        );
    }
    if (recipientEmails.length) {
        postData.partner_emails = recipientEmails;
    }
    const params = {
        // Changed in 18.2+: finally get rid of autofollow, following should be done manually
        post_data: postData,
        thread_id: thread.id,
        thread_model: thread.model,
    };
    if (cannedResponseIds?.length) {
        params.canned_response_ids = cannedResponseIds;
    }
    return params;
}
