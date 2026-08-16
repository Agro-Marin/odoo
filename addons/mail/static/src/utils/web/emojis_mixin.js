/** @odoo-module native */
import { EMOJI_REGEX } from "@mail/utils/common/format";
import { markup } from "@odoo/owl";
import { htmlReplace, htmlReplaceAll } from "@web/core/utils/dom/html";
/**
 * @param {string|ReturnType<markup>} message
 * @returns {ReturnType<markup>}
 */
export function formatText(message) {
    message = htmlReplaceAll(
        message,
        EMOJI_REGEX,
        /** @param {string} compoundEmoji */
        (compoundEmoji) => markup`<span class='o_mail_emoji'>${compoundEmoji}</span>`,
    );
    return htmlReplace(message, /(?:\r\n|\r|\n)/g, () => markup`<br>`);
}
