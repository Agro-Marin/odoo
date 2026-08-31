/** @odoo-module native */
import { MediaDialog, TABS } from "@html_editor/main/media/media_dialog/media_dialog";
import { patch } from "@web/core/utils/patch";

patch(MediaDialog.prototype, {
    /**
     * An image chosen to stand in for a social icon is marked as such, and
     * inherits the size class the icon it replaces was carrying, so the
     * snippet's own Layout and Size options keep addressing it.
     */
    extraClassesToAdd() {
        const classes = super.extraClassesToAdd();
        const closestDivEl = this.props.node?.parentElement.closest("div");
        if (
            this.state.activeTab === TABS.IMAGES.id &&
            closestDivEl?.matches(".s_social_media, .s_share")
        ) {
            classes.push("social_media_img");
            for (const className of this.props.node.classList) {
                if (className.match(/fa-\d{1}x/) || className === "small_social_icon") {
                    classes.push(className);
                }
            }
        }
        return classes;
    },
});
