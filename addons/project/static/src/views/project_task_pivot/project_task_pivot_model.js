/** @odoo-module native */
import { PivotModel } from "@web/views/pivot";

import { ProjectTaskModelMixin } from "../project_task_model_mixin.js";

export class ProjectTaskPivotModel extends ProjectTaskModelMixin(PivotModel) {}
