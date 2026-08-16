/** @odoo-module native */
import { LinkNavigation } from "@mail/core/common/link_navigation_service";
import { patch } from "@web/core/utils/patch";

patch(LinkNavigation.prototype, {
    /**
     * @param {MouseEvent} ev
     * @param {import("models").Thread} [thread]
     * @returns {boolean}
     */
    handleClickOnLink(ev, thread) {
        const model = ev.target.dataset.oeModel;
        const id = Number(ev.target.dataset.oeId);
        const isLinkHandledBySuper = super.handleClickOnLink(...arguments);
        if (!isLinkHandledBySuper && ev.target.tagName === "A" && id && model) {
            ev.preventDefault();
            Promise.resolve(
                this.env.services.action.doAction({
                    type: "ir.actions.act_window",
                    res_model: model,
                    views: [[false, "form"]],
                    res_id: id,
                }),
            ).then(() => this.onLinkFollowed(thread));
            return true;
        }
        return false;
    },
});
