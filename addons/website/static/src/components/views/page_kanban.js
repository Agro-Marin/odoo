/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { usePageManager } from "./page_manager_hook.js";
import { PageSearchModel } from "./page_search_model.js";

const log = makeLogger("website.view.page_kanban");

export class PageKanbanController extends kanbanView.Controller {
    static components = {
        ...kanbanView.Controller.components,
    };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.pageManager = usePageManager({
            resModel: this.props.resModel,
            createAction: this.props.context.create_action,
        });
    }
    /**
     * @override
     */
    async createRecord() {
        log.logic("createRecord", () => ({ resModel: this.props.resModel }));
        return this.pageManager.createWebsiteContent();
    }
}

export const PageKanbanView = {
    ...kanbanView,
    Controller: PageKanbanController,
    SearchModel: PageSearchModel,
};

registry.category("views").add("website_pages_kanban", PageKanbanView);
