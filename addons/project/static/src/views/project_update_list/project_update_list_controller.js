/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list";

import { ProjectRightSidePanel } from "../../components/project_right_side_panel/project_right_side_panel.js";

export class ProjectUpdateListController extends ListController {
    static template = "project.ProjectUpdateListView";
    static components = {
        ...ListController.components,
        ProjectRightSidePanel,
    };
    setup() {
        super.setup();
        this.ui = useService("ui");
    }

    get className() {
        return super.className + " o_controller_with_rightpanel";
    }
}
