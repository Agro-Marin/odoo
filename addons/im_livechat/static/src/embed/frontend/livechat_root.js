/** @odoo-module native */
import { LivechatButton } from "@im_livechat/embed/common/livechat_button";
import { ChatHub } from "@mail/core/common/chat_hub";
import { provideMailContext } from "@mail/utils/common/mail_context";
import { Component, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { OverlayContainer } from "@web/ui/overlay/overlay_container";

export class LivechatRoot extends Component {
    static template = xml`
        <ChatHub/>
        <OverlayContainer overlays="this.overlayService.overlays"/>
    `;
    static components = { ChatHub, LivechatButton, OverlayContainer };
    static props = {};

    setup() {
        provideMailContext({ embedLivechat: true });
        this.overlayService = useService("overlay");
    }
}
