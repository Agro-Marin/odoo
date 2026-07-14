/** @odoo-module native */
import { PivotModel } from "@web/views/pivot/pivot_model";
import { ProjectTaskModelMixin } from "../project_task_model_mixin.js";

export class ProjectTaskAnalysisPivotModel extends ProjectTaskModelMixin(PivotModel) {}
