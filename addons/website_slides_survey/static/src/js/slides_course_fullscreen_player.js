/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { renderToElement } from "@web/core/utils/render";
import { FullscreenPlayer } from "@website_slides/interactions/fullscreen_player";

patch(FullscreenPlayer.prototype, {
    /**
     * Extend the _renderSlide method so that slides of category
     * "certification" are also taken into account and rendered correctly.
     *
     * @override
     */
    async _renderSlide() {
        const res = await super._renderSlide(...arguments);
        if (this._slideValue.category === "certification") {
            const contentEl = this.el.querySelector(".o_wslides_fs_content");
            contentEl.textContent = "";
            contentEl.append(
                renderToElement("website.slides.fullscreen.certification", {
                    widget: this,
                }),
            );
        }
        return res;
    },
});
