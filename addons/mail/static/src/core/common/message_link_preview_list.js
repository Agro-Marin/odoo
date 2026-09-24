// @ts-check
/** @odoo-module native */
import { LinkPreview } from "@mail/core/common/link_preview";
import { useMailContext } from "@mail/utils/common/mail_context";
import { Component } from "@odoo/owl";

/**
 * @typedef {Object} Props
 * @property {import("models").MessageLinkPreview[]} messageLinkPreviews
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class MessageLinkPreviewList extends Component {
    static template = "mail.MessageLinkPreviewList";
    static props = ["messageLinkPreviews"];
    static components = { LinkPreview };

    setup() {
        super.setup();
        this.mailContext = useMailContext();
    }
}
