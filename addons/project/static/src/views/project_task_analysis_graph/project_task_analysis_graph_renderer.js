/** @odoo-module native */
import { GraphRenderer } from "@web/views/graph";

import { ProjectTaskAnalysisRendererMixin } from "../project_task_analysis_renderer_mixin.js";

export class ProjectTaskAnalysisGraphRenderer extends ProjectTaskAnalysisRendererMixin(
    GraphRenderer,
) {}
