/** @odoo-module native */
import { ActivityModel } from "@mail/views/web/activity/activity_model";
import { ProjectTaskModelMixin } from "../project_task_model_mixin.js";

export class ProjectTaskActivityModel extends ProjectTaskModelMixin(ActivityModel) {}
