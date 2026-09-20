/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { Animation } from "@website/interactions/animation";

patch(Animation.prototype, {
    /**
     * @override
     */
    findScrollingElement() {
        const articleContent = document.querySelector(".o_wslide_fs_article_content");
        return articleContent
            ? articleContent
            : super.findScrollingElement(...arguments);
    },
});
