/** @odoo-module native */
import { activityView } from "@mail/views/web/activity/activity_view";
import { registry } from "@web/core/registry";

import { HighlightProjectTaskSearchModel } from "../highlight_project_task_search_model.js";
import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskActivityModel } from "./project_task_activity_model.js";

export const projectTaskActivityView = {
    SearchModel: HighlightProjectTaskSearchModel,
    ...activityView,
    ControlPanel: ProjectTaskControlPanel,
    Model: ProjectTaskActivityModel,
};

registry.category("views").add("project_task_activity", projectTaskActivityView);
