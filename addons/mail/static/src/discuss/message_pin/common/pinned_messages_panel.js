/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { MessageCardList } from "@mail/core/common/message_card_list";
import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { _t } from "@web/core/translation";
/**
 * @typedef {Object} Props
 * @property {import("models").Thread} thread
 * @property {string} [className]
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class PinnedMessagesPanel extends Component {
    static components = {
        MessageCardList,
        ActionPanel,
    };
    static props = ["thread", "className?"];
    static template = "discuss.PinnedMessagesPanel";

    setup() {
        super.setup();
        onWillStart(() => {
            this.props.thread.fetchPinnedMessages();
        });
        onWillUpdateProps(
            /** @param {{thread: import("models").Thread}} nextProps */ (nextProps) => {
                if (nextProps.thread.notEq(this.props.thread)) {
                    nextProps.thread.fetchPinnedMessages();
                }
            },
        );
    }

    get emptyText() {
        if (this.props.thread.pinnedMessagesState === "error") {
            return _t("Pinned messages could not be loaded.");
        }
        if (this.props.thread.channel_type === "channel") {
            return _t("This channel doesn't have any pinned messages.");
        } else {
            return _t("This conversation doesn't have any pinned messages.");
        }
    }
}
