// @ts-check
/** @odoo-module native */
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";

const log = makeLogger("mail.link_preview");
/**
 * @typedef {Object} Props
 * @property {import("models").MessageLinkPreview} linkPreview
 * @property {function} [delete]
 * @property {function} [deleteAll]
 * @property {function} close
 * @property {Component} LinkPreviewListComponent
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class LinkPreviewConfirmDelete extends Component {
    static components = { Dialog };
    static props = ["linkPreview", "delete", "deleteAll?", "close", "LinkPreview"];
    static template = "mail.LinkPreviewConfirmDelete";

    setup() {
        super.setup();
        this.store = useService("mail.store");
    }

    get message() {
        return this.props.linkPreview.message_id;
    }

    onClickOk() {
        log.logic("delete link preview", () => ({
            linkPreviewId: this.props.linkPreview.id,
            messageId: this.message?.id,
        }));
        this.props.delete();
        this.props.close();
    }

    onClickDeleteAll() {
        log.logic("delete all link previews", () => ({ messageId: this.message?.id }));
        this.props.deleteAll?.();
        this.props.close();
    }

    onClickCancel() {
        this.props.close();
    }
}
