// @ts-check
/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { useMailContext } from "@mail/utils/common/mail_context";
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

const log = makeLogger("mail.thread");
export class DeleteThreadDialog extends Component {
    static components = { ActionPanel };
    static props = ["thread", "close"];
    static template = "discuss.DeleteThreadDialog";

    setup() {
        super.setup();
        this.mailContext = useMailContext();
        this.notification = useService("notification");
        this.store = useService("mail.store");
    }

    async onConfirmation() {
        let toOpenThread;
        const threadName = this.props.thread.name;
        if (
            this.store.discuss?.thread?.eq(this.props.thread) ||
            this.mailContext.inChatWindow
        ) {
            toOpenThread = this.props.thread.parent_channel_id;
        }
        log.logic("delete sub channel", () => ({
            thread: this.props.thread.localId,
            reopen: toOpenThread?.localId,
        }));
        await rpc("/discuss/channel/sub_channel/delete", {
            sub_channel_id: this.props.thread.id,
        });
        if (toOpenThread?.exists()) {
            toOpenThread.open();
        }
        this.props.close();
        this.notification.add(
            _t('Thread "%(thread_name)s" has been deleted', {
                thread_name: threadName,
            }),
            { type: "info" },
        );
    }
}
