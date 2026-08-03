/** @odoo-module native */
import { GraphModel } from "@web/views/graph";

import { ProjectTaskModelMixin } from "../project_task_model_mixin.js";

export class ProjectTaskGraphModel extends ProjectTaskModelMixin(GraphModel) {}
