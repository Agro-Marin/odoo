/** @odoo-module native */
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { ProjectTaskModelMixin } from "./project_task_model_mixin.js";

export class ProjectTaskRelationalModel extends ProjectTaskModelMixin(RelationalModel) {}
