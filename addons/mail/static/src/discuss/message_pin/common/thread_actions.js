// @ts-check
/** @odoo-module native */
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { PinnedMessagesPanel } from "@mail/discuss/message_pin/common/pinned_messages_panel";
import { provideChildMailContext } from "@mail/utils/common/mail_context";
import { _t } from "@web/core/translation";

/** @typedef {import("@mail/core/common/thread_actions").ActionParams} ActionParams */
registerThreadAction("pinned-messages", {
    actionPanelComponent: PinnedMessagesPanel,
    /** @param {ActionParams} params */
    condition: ({ owner, thread }) =>
        thread?.isChannelKind &&
        (!owner.props.chatWindow || owner.props.chatWindow.isOpen) &&
        !owner.isDiscussSidebarChannelActions,
    panelOuterClass: "o-discuss-PinnedMessagesPanel bg-inherit",
    icon: "fa-solid fa-thumbtack",
    /** @param {ActionParams} params */
    name: ({ action }) =>
        action.isActive ? _t("Hide Pinned Messages") : _t("Pinned Messages"),
    sequence: 20,
    sequenceGroup: 10,
    setup() {
        provideChildMailContext({
            pinMenu: {
                open: () => this.open(),
                close: () => {
                    if (this.isActive) {
                        this.close();
                    }
                },
            },
        });
    },
    toggle: true,
});
