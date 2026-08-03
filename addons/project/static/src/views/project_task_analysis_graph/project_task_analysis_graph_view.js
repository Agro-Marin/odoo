/** @odoo-module native */
import { registry } from "@web/core/registry";
import { graphView } from "@web/views/graph";

import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskAnalysisGraphModel } from "./project_task_analysis_graph_model.js";
import { ProjectTaskAnalysisGraphRenderer } from "./project_task_analysis_graph_renderer.js";

registry.category("views").add("project_task_analysis_graph", {
    ...graphView,
    ControlPanel: ProjectTaskControlPanel,
    Model: ProjectTaskAnalysisGraphModel,
    Renderer: ProjectTaskAnalysisGraphRenderer,
});
