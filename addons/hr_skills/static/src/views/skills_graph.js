/** @odoo-module native */
import { registry } from "@web/core/registry";
import { GraphRenderer, graphView } from "@web/views/graph";

export class SkillsGraphRenderer extends GraphRenderer {
    getScaleOptions() {
        const scaleOptions = super.getScaleOptions();

        if ('y' in scaleOptions) {
            scaleOptions.y.suggestedMax = 100;
        }

        return scaleOptions;
    }
}

export const skillsGraphView = {
    ...graphView,
    Renderer: SkillsGraphRenderer,
};

registry.category("views").add("skills_graph", skillsGraphView);
