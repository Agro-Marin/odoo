/** @odoo-module native */
import { MessageConfirmDialog } from "@mail/core/common/message_confirm_dialog";
import { Message } from "@mail/core/common/message_model";
import { fields } from "@mail/core/common/record";
import { _t } from "@web/core/translation";
import { Deferred } from "@web/core/utils/concurrency";
import { patch } from "@web/core/utils/patch";
patch(Message.prototype, {
    setup() {
        super.setup();
        this.pinned_at = fields.Datetime();
        this.threadAsPinned = fields.One("Thread", {
            /** @this {import("models").Message} */
            compute() {
                return this.pinned_at ? this.thread : undefined;
            },
            inverse: "pinnedMessages",
        });
    },
    /** @returns {Deferred<boolean>} */
    pin() {
        if (this.pinned_at) {
            return this.unpin();
        }
        if (this.thread?.model !== "discuss.channel") {
            return this._setPin(true, _t("Message pinned"), () => this.unpin());
        }
        const def = new Deferred();
        this.store.env.services.dialog.add(
            MessageConfirmDialog,
            {
                confirmText: _t("Yeah, pin it!"),
                message: this,
                prompt: _t(
                    "You sure want this message pinned to %(conversation)s forever and ever?",
                    {
                        conversation: this.thread.prefix + this.thread.displayName,
                    },
                ),
                size: "md",
                title: _t("Pin It"),
                onConfirm: () => {
                    def.resolve(true);
                    this.thread.setMessagePin(this, true);
                },
            },
            { onClose: () => def.resolve(false) },
        );
        return def;
    },
    /** @returns {Deferred<boolean>} */
    unpin() {
        if (this.thread?.model !== "discuss.channel") {
            return this._setPin(false, _t("Message unpinned"), () => this.pin());
        }
        const def = new Deferred();
        this.store.env.services.dialog.add(
            MessageConfirmDialog,
            {
                confirmColor: "btn-danger",
                confirmText: _t("Yes, remove it please"),
                message: this,
                prompt: _t(
                    "Well, nothing lasts forever, but are you sure you want to unpin this message?",
                ),
                size: "md",
                title: _t("Unpin Message"),
                onConfirm: () => {
                    def.resolve(true);
                    this.thread.setMessagePin(this, false);
                },
            },
            { onClose: () => def.resolve(false) },
        );
        return def;
    },
    /**
     * Outside a channel nobody else is watching, so the toggle is immediate
     * and the way back is an Undo on the confirmation instead of a prompt.
     *
     * @returns {Deferred<boolean>}
     */
    _setPin(pinned, notificationText, undo) {
        const def = new Deferred();
        const thread = this.thread;
        thread.setMessagePin(this, pinned).then(() => {
            def.resolve(true);
            const closeFn = this.store.env.services.notification.add(notificationText, {
                buttons: [
                    {
                        name: _t("Undo"),
                        onClick: () => {
                            undo();
                            closeFn();
                        },
                    },
                ],
                type: "success",
            });
        });
        return def;
    },
});
