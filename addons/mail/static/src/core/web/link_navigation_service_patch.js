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
        // See the base implementation: `ev.target` is the shadow HOST for a
        // link inside an email message body, so this read answered undefined
        // and record links never opened.
        const target = /** @type {HTMLElement} */ (ev.composedPath?.()[0] ?? ev.target);
        const model = target.dataset?.oeModel;
        const id = Number(target.dataset?.oeId);
        const isLinkHandledBySuper = super.handleClickOnLink(...arguments);
        if (!isLinkHandledBySuper && target.tagName === "A" && id && model) {
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
