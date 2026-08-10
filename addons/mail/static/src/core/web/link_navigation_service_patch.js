/** @odoo-module native */
import { LinkNavigation } from "@mail/core/common/link_navigation_service";
import { patch } from "@web/core/utils/patch";

/**
 * Backend-only fallback: a link the common layer did not claim, but that names a
 * record (`data-oe-model` + `data-oe-id`), opens that record's form view.
 *
 * This cannot live in `core/common`: the public discuss page has no action
 * service to `doAction` with. It reads the dataset off `ev.target` rather than
 * off the resolved anchor on purpose — that is the pre-existing behaviour, and
 * it differs from `super`, which resolves through `closest("a")`.
 */
patch(LinkNavigation.prototype, {
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
