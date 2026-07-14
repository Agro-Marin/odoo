/** @odoo-module native */
import { WebChatter } from "@mail/chatter/web/web_chatter";
import { AttachmentView } from "@mail/core/common/attachment_view";
import { useState } from "@odoo/owl";
import { router } from "@web/core/browser/router";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { SIZES } from "@web/ui/block/ui_service";
import { FormRenderer } from "@web/views/form/form_renderer";
patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        this.mailComponents = {
            AttachmentView,
            // key stays "Chatter": the form compiler and downstream tooling
            // (e.g. web_studio) target `mailComponents.Chatter`.
            Chatter: WebChatter,
        };
        this.highlightMessageId = router.current.highlight_message_id;
        this.messagingState = useState({
            /** @type {import("models").Thread} */
            thread: undefined,
        });
        if (this.env.services["mail.store"]) {
            this.mailStore = useService("mail.store");
        }
        this.uiService = useService("ui");
        this.mailPopoutService = useService("mail.popout");
        // mailLayout only depends on breakpoints: the base FormRenderer already
        // re-renders on the ui service's breakpoint RESIZE event.
    },
    /**
     * @returns {boolean}
     */
    hasFile() {
        if (!this.mailStore || !this.props.record.resId) {
            return false;
        }
        this.messagingState.thread = this.mailStore.Thread.insert({
            id: this.props.record.resId,
            model: this.props.record.resModel,
        });
        return this.messagingState.thread.attachmentsInWebClientView.length > 0;
    },
    mailLayout(hasAttachmentContainer) {
        const xxl = this.uiService.size >= SIZES.XXL;
        const hasFile = this.hasFile();
        const hasChatter = !!this.mailStore;
        const hasExternalWindow = !!this.mailPopoutService.externalWindow;
        if (hasExternalWindow && hasFile && hasAttachmentContainer) {
            if (xxl) {
                return "EXTERNAL_COMBO_XXL"; // chatter on the side, attachment in separate tab
            }
            return "EXTERNAL_COMBO"; // chatter on the bottom, attachment in separate tab
        }
        if (hasChatter) {
            if (xxl) {
                if (hasAttachmentContainer && hasFile) {
                    return "COMBO"; // chatter on the bottom, attachment on the side
                }
                return "SIDE_CHATTER"; // chatter on the side, no attachment
            }
            return "BOTTOM_CHATTER"; // chatter on the bottom, no attachment
        }
        return "NONE";
    },
});
