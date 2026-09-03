/** @odoo-module native */
import { Composer } from "@mail/core/common/composer";
import { markup } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
/** @type {Composer} */
const composerPatch = {
    /** @param {import("@mail/discuss/gif_picker/common/gif_picker").TenorGif} gif */
    async sendGifMessage(gif) {
        const gifUrl = gif.media_formats.tinygif.url;
        const href = encodeURI(gifUrl);
        await this._sendMessage(
            markup`<a href="${href}" target="_blank" rel="noreferrer noopener">${gifUrl}</a>`,
            { parentId: this.props.composer.replyToMessage?.id },
        );
    },
};
patch(Composer.prototype, composerPatch);
