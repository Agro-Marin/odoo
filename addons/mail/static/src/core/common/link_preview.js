/** @odoo-module native */
import { Gif } from "@mail/core/common/gif";
import { LinkPreviewConfirmDelete } from "@mail/core/common/link_preview_confirm_delete";
import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {Object} Props
 * @property {import("models").LinkPreview} linkPreview
 * @property {import("models").Message} [message]
 * @property {Boolean} [gifPaused]
 * @property {function} [delete] Function bound to the delete button
 * @property {function} [deleteAll] Function bound to the delete all button
 * @extends {Component<Props, Env>}
 */
export class LinkPreview extends Component {
    static template = "mail.LinkPreview";
    static props = ["linkPreview", "delete?", "deleteAll?", "gifPaused?", "message?"];
    static components = { Gif };

    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.state = useState({ startVideo: false, videoLoaded: false });
        this.videoRef = useRef("video");
        useEffect(
            (el) => {
                if (!el) {
                    return;
                }
                el.onload = () => (this.state.videoLoaded = true);
                // Reveal the player even if the embed never fires `load`
                // (blocked embed, CSP, network error); otherwise the iframe
                // stays permanently `d-none` and the user clicks play to see
                // nothing, with no way to recover.
                el.onerror = () => (this.state.videoLoaded = true);
                return () => {
                    el.onload = null;
                    el.onerror = null;
                };
            },
            () => [this.videoRef.el],
        );
    }

    onClick() {
        this.dialogService.add(LinkPreviewConfirmDelete, {
            linkPreview: this.props.linkPreview,
            delete: this.props.delete,
            deleteAll: this.props.deleteAll,
            LinkPreview,
        });
    }

    onImageLoaded() {
        this.env.onImageLoaded?.();
    }
}
