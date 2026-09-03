/** @odoo-module native */
import { WebChatter } from "@mail/chatter/web/web_chatter";
import { AttachmentView } from "@mail/core/common/attachment_view";
import { onWillRender, useState } from "@odoo/owl";
import { router } from "@web/core/browser/router";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { SIZES } from "@web/ui/viewport";
import { FormRenderer } from "@web/views/form";
patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        this.mailComponents = {
            AttachmentView,
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
        onWillRender(() => this.syncMessagingThread());
    },
    syncMessagingThread() {
        const { resId, resModel } = this.props.record;
        if (!this.mailStore || !resId) {
            this.messagingState.thread = undefined;
            return;
        }
        const thread = this.messagingState.thread;
        if (thread?.id === resId && thread.model === resModel) {
            return;
        }
        this.messagingState.thread = this.mailStore.Thread.insert({
            id: resId,
            model: resModel,
        });
    },
    /** @returns {boolean} */
    hasFile() {
        return (this.messagingState.thread?.attachmentsInWebClientView.length ?? 0) > 0;
    },
    /**
     * @param {boolean} hasAttachmentContainer
     * @returns {string}
     */
    mailLayout(hasAttachmentContainer) {
        const xxl = this.uiService.size >= SIZES.XXL;
        const hasFile = this.hasFile();
        const hasChatter = !!this.mailStore;
        const hasExternalWindow = !!this.mailPopoutService.externalWindow;
        if (hasExternalWindow && hasFile && hasAttachmentContainer) {
            if (xxl) {
                return "EXTERNAL_COMBO_XXL";
            }
            return "EXTERNAL_COMBO";
        }
        if (hasChatter) {
            if (xxl) {
                if (hasAttachmentContainer && hasFile) {
                    return "COMBO";
                }
                return "SIDE_CHATTER";
            }
            return "BOTTOM_CHATTER";
        }
        return "NONE";
    },
});
