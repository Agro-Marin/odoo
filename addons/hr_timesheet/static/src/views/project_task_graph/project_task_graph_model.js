/** @odoo-module native */
import { ProjectTaskGraphModel } from "@project/views/project_task_graph/project_task_graph_model";
import { patchGraphModel } from "../graph_model_patch.js";

patchGraphModel(ProjectTaskGraphModel);
