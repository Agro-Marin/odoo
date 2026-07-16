/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";

import { usePageManager } from "./page_manager_hook.js";
import { PageSearchModel } from "./page_search_model.js";

export class PageKanbanController extends kanbanView.Controller {
    static components = {
        ...kanbanView.Controller.components,
    };

    setup() {
        super.setup();
        this.pageManager = usePageManager({
            resModel: this.props.resModel,
            createAction: this.props.context.create_action,
        });
    }
    /**
     * @override
     */
    async createRecord() {
        return this.pageManager.createWebsiteContent();
    }
}

export const PageKanbanView = {
    ...kanbanView,
    Controller: PageKanbanController,
    SearchModel: PageSearchModel,
};

registry.category("views").add("website_pages_kanban", PageKanbanView);
