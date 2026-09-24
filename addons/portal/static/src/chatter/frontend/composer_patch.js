/** @odoo-module native */
import { Composer } from "@mail/core/common/composer";
import { useMailContext } from "@mail/utils/common/mail_context";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    setup() {
        super.setup(...arguments);
        this.mailContext = useMailContext();
    },

    get showComposerAvatar() {
        return (
            super.showComposerAvatar ||
            (this.props.mode === "compact" && this.props.composer.portalComment)
        );
    },

    get shouldHideFromMessageListOnDelete() {
        return (
            this.mailContext.inFrontendPortalChatter ||
            super.shouldHideFromMessageListOnDelete
        );
    },
});
