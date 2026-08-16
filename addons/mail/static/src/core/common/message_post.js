/** @odoo-module native */
import { generateEmojisOnHtml } from "@mail/utils/common/format";
import { createDocumentFragmentFromContent, isMarkup } from "@web/core/utils/dom/html";
import { renderToElement } from "@web/core/utils/render";

/** @param {HTMLAnchorElement[]} channelLinks */
export function handleValidChannelMention(channelLinks) {
    for (const linkEl of channelLinks.filter(
        (el) => !el.querySelector(".fa-comments-o, .fa-hashtag"),
    )) {
        const text = linkEl.textContent.substring(1);
        const icon = linkEl.classList.contains("o_channel_redirect_asThread")
            ? "fa-regular fa-comments"
            : "fa-solid fa-hashtag";
        const iconEl = renderToElement("mail.Message.mentionedChannelIcon", { icon });
        linkEl.replaceChildren(iconEl);
        linkEl.insertAdjacentText("beforeend", ` ${text}`);
    }
}

/**
 * @typedef {Object} MessagePostData
 * @property {import("models").Attachment[]} [attachments]
 * @property {number[]} [cannedResponseIds]
 * @property {boolean} [emailAddSignature]
 * @property {boolean} [isNote]
 * @property {import("models").Thread[]} [mentionedChannels]
 * @property {import("models").ResPartner[]} [mentionedPartners]
 * @property {import("models").ResRole[]} [mentionedRoles]
 * @property {string|ReturnType<import("@odoo/owl").markup>} [body]
 * @property {boolean} [email_add_signature]
 * @property {string} [message_type]
 * @property {string} [subtype_xmlid]
 * @property {number[]} [attachment_ids]
 * @property {string[]} [attachment_tokens]
 * @property {number[]} [partner_ids]
 * @property {Object<number, string>} [partner_ids_mention_token]
 * @property {number[]} [role_ids]
 * @property {string[]} [special_mentions]
 * @property {string[]} [partner_emails]
 */
/**
 * @param {import("models").Store} store
 * @param {MessagePostData} postData
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
 * @param {import("models").Store} store
 * @param {string|ReturnType<import("@odoo/owl").markup>} body
 * @param {Object} [options]
 * @param {import("models").Thread[]} [options.mentionedChannels=[]]
 * @param {import("models").ResPartner[]} [options.mentionedPartners=[]]
 * @param {import("models").ResRole[]} [options.mentionedRoles=[]]
 * @param {import("models").Thread} [options.thread]
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
              /** @param {HTMLAnchorElement} a */ (a) => a.textContent,
          )
        : [/** @type {string} */ (body)];
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

/** @type {Set<string>} */
const CLIENT_ONLY_POST_DATA_KEYS = new Set([
    "attachments",
    "cannedResponseIds",
    "emailAddSignature",
    "isNote",
    "mentionedChannels",
    "mentionedPartners",
    "mentionedRoles",
    "parentId",
]);

/**
 * @param {import("models").Store} store
 * @param {Object} param1
 * @param {string|ReturnType<import("@odoo/owl").markup>} param1.body
 * @param {MessagePostData} param1.postData
 * @param {import("models").Thread} param1.thread
 * @returns {Promise<{ post_data: MessagePostData, thread_id: number, thread_model: string, canned_response_ids?: number[], }>}
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
    /** @type {string[]} */
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
        ...Object.fromEntries(
            Object.entries(postData).filter(
                ([key]) => !CLIENT_ONLY_POST_DATA_KEYS.has(key),
            ),
        ),
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
        post_data: postData,
        thread_id: thread.id,
        thread_model: thread.model,
    };
    if (cannedResponseIds?.length) {
        params.canned_response_ids = cannedResponseIds;
    }
    return params;
}
