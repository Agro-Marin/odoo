/** @odoo-module native */
import { registry } from "@web/core/registry";
import { pivotView } from "@web/views/pivot";

import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskAnalysisPivotModel } from "./project_task_analysis_pivot_model.js";
import { ProjectTaskAnalysisPivotRenderer } from "./project_task_analysis_pivot_renderer.js";

registry.category("views").add("project_task_analysis_pivot", {
    ...pivotView,
    ControlPanel: ProjectTaskControlPanel,
    Model: ProjectTaskAnalysisPivotModel,
    Renderer: ProjectTaskAnalysisPivotRenderer,
});
