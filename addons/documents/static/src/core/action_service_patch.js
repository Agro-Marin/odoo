/** @odoo-module native */
import { actionService } from "@web/webclient/actions";
import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";

/**
 * Saves the documents current view mode (only kanban or list)
 * in local storage to keep track of the user preferred mode.
 * Not applied in mobile environments (uses the "mobile_view_mode"
 * action field which defaults on "kanban").
 */
patch(actionService, {
    start(env) {
        const superReturn = super.start(env);
        // ``switchView`` is now a method on the ActionManager class instance,
        // so it must keep its ``this`` binding when captured and re-invoked
        // (the legacy closure-factory let it be called detached).
        const superSwitchView = superReturn.switchView.bind(superReturn);

        superReturn.switchView = async (viewType, props = {}, { newWindow } = {}) => {
            if (!env.isSmall && superReturn.currentController?.action?.xml_id === "documents.document_action") {
                const defaultViewType = browser.localStorage.getItem("documentsDefaultViewType");
                if (["kanban", "list"].includes(viewType) && defaultViewType !== viewType) {
                    browser.localStorage.setItem("documentsDefaultViewType", viewType);
                }
            }
            return superSwitchView(viewType, props, { newWindow });
        };
        return superReturn;
    },
});
