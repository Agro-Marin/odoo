/** @odoo-module */
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";
import { ProjectTaskAnalysisRendererMixin } from "../project_task_analysis_renderer_mixin.js";

export class ProjectTaskAnalysisPivotRenderer extends ProjectTaskAnalysisRendererMixin(PivotRenderer) {}
