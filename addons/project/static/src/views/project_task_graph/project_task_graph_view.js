/** @odoo-module native */
import { registry } from "@web/core/registry";
import { graphView } from "@web/views/graph";

import { HighlightProjectTaskSearchModel } from "../highlight_project_task_search_model.js";
import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskGraphModel } from "./project_task_graph_model.js";

export const projectTaskGraphView = {
    SearchModel: HighlightProjectTaskSearchModel,
    ...graphView,
    ControlPanel: ProjectTaskControlPanel,
    Model: ProjectTaskGraphModel,
};

registry.category("views").add("project_task_graph", projectTaskGraphView);
