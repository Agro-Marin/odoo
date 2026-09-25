/** @odoo-module native */
import { Discuss } from "@mail/core/public_web/discuss";
import { onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { FormRenderer } from "@web/views/form";

export class LivechatSessionFormRenderer extends FormRenderer {
    static template = "im_livechat.LivechatDiscuss";
    static components = {
        ...FormRenderer.components,
        Discuss,
    };

    setup() {
        super.setup();
        this.action = useService("action");
        this.store = useState(useService("mail.store"));
        useLayoutEffect(
            (thread) => {
                if (thread) {
                    thread.shadowedBySelf++;
                    return () => thread.shadowedBySelf--;
                }
            },
            () => [this.thread],
        );
        onWillStart(() => this.getChannel(this.props));
        onWillUpdateProps(async (nextProps) => {
            if (nextProps.record.resId === this.props.record.resId) {
                return;
            }
            await this.getChannel(nextProps);
        });
    }

    /**
     * @param {Props} props
     */
    async getChannel(props) {
        this.thread = await this.store.Thread.getOrFetch({
            model: "discuss.channel",
            id: props.record.resId,
        });
    }

    redirectToSessions() {
        this.action.doAction("im_livechat.discuss_channel_action", {
            clearBreadcrumbs: true,
        });
    }
}
