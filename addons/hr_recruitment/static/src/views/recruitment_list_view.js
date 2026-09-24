/** @odoo-module native */
import { registry } from "@web/core/registry";

import { listView, ListRenderer } from "@web/views/list";
import { RecruitmentActionHelper } from "@hr_recruitment/views/recruitment_helper_view";
import { RecruitmentListController } from "@hr_recruitment/views/recruitment_list_controller";
import { useDebugMode } from "@web/core/debug/debug_context";

export class RecruitmentListRenderer extends ListRenderer {
    static template = "hr_recruitment.RecruitmentListRenderer";
    static components = {
        ...ListRenderer.components,
        RecruitmentActionHelper,
    };

    setup() {
        super.setup();
        this.debug = useDebugMode();
    }
}

export const RecruitmentListView = {
    ...listView,
    Controller: RecruitmentListController,
    Renderer: RecruitmentListRenderer,
};

registry.category("views").add("recruitment_list_view", RecruitmentListView);
