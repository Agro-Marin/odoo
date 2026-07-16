/** @odoo-module native */
import { ImageSelector as HtmlImageSelector } from "@html_editor/main/media/media_dialog/image_selector";
import { patch } from "@web/core/utils/patch";

patch(HtmlImageSelector.prototype, {
    get attachmentsDomain() {
        const domain = super.attachmentsDomain;
        domain.push("|", ["url", "=", false], "!", [
            "url",
            "=like",
            "/web/image/website.%",
        ]);
        domain.push(["key", "=", false]);
        return domain;
    },
});
