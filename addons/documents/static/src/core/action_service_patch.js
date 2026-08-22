/** @odoo-module native */
import { actionService } from "@web/webclient/actions";
import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";

patch(actionService, {
    start(env) {
        const superReturn = super.start(env);
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
