// @ts-check
/** @odoo-module native */
import { Discuss } from "@mail/core/public_web/discuss";
import { MessagingMenu } from "@mail/core/public_web/messaging_menu";
import { _t } from "@web/core/translation";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { patch } from "@web/core/utils/patch";
import { useViewConfig } from "@web/core/view_config_hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
Object.assign(Discuss.components, { ControlPanel, MessagingMenu });

patch(Discuss.prototype, {
    setup() {
        super.setup();
        this.config = useViewConfig();
        this.prevInboxCounter = this.store.inbox.counter;
        useLayoutEffect(
            /** @param {string|undefined} threadName */
            (threadName) => {
                if (threadName) {
                    this.config?.setDisplayName(threadName);
                }
            },
            () => [this.thread?.displayName],
        );
        useLayoutEffect(
            () => {
                if (
                    this.thread?.id === "inbox" &&
                    this.prevInboxCounter !== this.store.inbox.counter &&
                    this.store.inbox.counter === 0
                ) {
                    this.effect.add({
                        message: _t("Congratulations, your inbox is empty!"),
                        type: "rainbow_man",
                        fadeout: "fast",
                    });
                }
                this.prevInboxCounter = this.store.inbox.counter;
            },
            () => [this.store.inbox.counter],
        );
    },
});
