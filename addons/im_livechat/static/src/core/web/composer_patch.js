/** @odoo-module native */
import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    onKeydown(ev) {
        super.onKeydown(ev);
        if (
            ev.key === "Tab" &&
            this.thread?.channel_type === "livechat" &&
            !this.props.composer.composerText
        ) {
            const threadChanged = this.store.goToOldestUnreadLivechatThread();
            if (threadChanged) {
                ev.stopPropagation();
            }
        }
    },
    get placeholder() {
        if (this.displayNextLivechatHint() && this.props.composer.isFocused) {
            return _t("Tab to next livechat");
        }
        return super.placeholder;
    },
    displayNextLivechatHint() {
        return (
            this.thread?.channel_type === "livechat" &&
            this.store.discuss.livechats.some(
                (thread) => thread.notEq(this.thread) && thread.isUnread,
            )
        );
    },
});
