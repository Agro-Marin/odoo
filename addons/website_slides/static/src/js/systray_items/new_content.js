/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import {
    MODULE_STATUS,
    NewContentSystrayItem,
} from "@website/client_actions/website_preview/new_content_systray_item";

patch(NewContentSystrayItem.prototype, {
    setup() {
        super.setup();

        const newSlidesChannelElement = this.state.newContentElements.find(
            (element) => element.moduleXmlId === "base.module_website_slides",
        );
        newSlidesChannelElement.createNewContent = () =>
            this.onAddContent("website_slides.slide_channel_action_add");
        newSlidesChannelElement.status = MODULE_STATUS.INSTALLED;
        newSlidesChannelElement.model = "slide.channel";
    },
});
