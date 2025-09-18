import { registerThreadAction, threadActionsRegistry } from "@mail/core/common/thread_actions";
import "@mail/discuss/call/common/thread_actions";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

registerThreadAction("restart", {
    condition: ({ owner, thread }) =>
        thread?.chatbot?.canRestart && !owner.isDiscussSidebarChannelActions,
    icon: "fa-solid fa-arrows-rotate",
    name: _t("Restart Conversation"),
    open: ({ owner, thread }) => {
        thread.chatbot.restart();
        owner.props.chatWindow.open({ focus: true });
    },
    sequence: 99,
    sequenceQuick: 15,
});

const callSettingsAction = threadActionsRegistry.get("call-settings");
patch(callSettingsAction, {
    condition({ store, thread }) {
        return thread?.channel_type === "livechat"
            ? store.rtc.state.channel?.eq(thread)
            : super.condition(...arguments);
    },
});
