/** @odoo-module native */
import { ActionList } from "@mail/core/common/action_list";
import { useThreadActions } from "@mail/core/common/thread_actions";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {Object} Props
 * @property {import("models").Thread} thread
 * @property {function} [close]
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class DiscussSidebarChannelActions extends Component {
    static template = "mail.DiscussSidebarChannelActions";
    static props = ["thread"];
    static components = { ActionList };

    setup() {
        this.store = useService("mail.store");
        this.isDiscussSidebarChannelActions = true;
        this.threadActions = useThreadActions({ thread: () => this.thread });
    }

    get thread() {
        return this.props.thread;
    }
}
