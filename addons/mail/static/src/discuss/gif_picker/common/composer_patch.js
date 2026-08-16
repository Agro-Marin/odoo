/** @odoo-module native */
import { Composer } from "@mail/core/common/composer";
import { markup, useRef } from "@odoo/owl";
import { markEventHandled } from "@web/core/utils/dom/events";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
/** @type {Composer} */
const composerPatch = {
    setup() {
        this.gifButton = useRef("gif-button");
        super.setup();
        this.ui = useService("ui");
    },
    get pickerSettings() {
        const setting = super.pickerSettings;
        if (this.hasGifPicker) {
            setting.pickers.gif =
                /** @param {import("@mail/discuss/gif_picker/common/gif_picker").TenorGif} gif */ (
                    gif,
                ) => this.sendGifMessage(gif);
            if (this.hasGifPickerButton) {
                setting.buttons.push(this.gifButton);
            }
        }
        return setting;
    },
    get hasGifPicker() {
        return (
            (this.store.hasGifPickerFeature ||
                this.store.self_partner?.main_user_id?.is_admin) &&
            !this.env.inChatter &&
            !this.props.composer.message
        );
    },
    get hasGifPickerButton() {
        return this.hasGifPicker && !this.ui.isSmall && !this.env.inChatWindow;
    },
    /** @param {MouseEvent} ev */
    onClickAddGif(ev) {
        markEventHandled(ev, "Composer.onClickAddGif");
    },
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
