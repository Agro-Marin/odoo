/** @odoo-module native */
import { registry } from "@web/core/registry";
import { pivotView } from "@web/views/pivot";

import { HighlightProjectTaskSearchModel } from "../highlight_project_task_search_model.js";
import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskPivotModel } from "./project_task_pivot_model.js";

export const projectTaskPivotView = {
    SearchModel: HighlightProjectTaskSearchModel,
    ...pivotView,
    ControlPanel: ProjectTaskControlPanel,
    Model: ProjectTaskPivotModel,
};

registry.category("views").add("project_task_pivot", projectTaskPivotView);
