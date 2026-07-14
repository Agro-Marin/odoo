/** @odoo-module native */
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { ProjectModelMixin } from "./project_model_mixin.js";

export class ProjectRelationalModel extends ProjectModelMixin(RelationalModel) {}
