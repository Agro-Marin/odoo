/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import {
    ProjectProfitability,
    projectProfitabilityProps,
} from "@project/components/project_right_side_panel/components/project_profitability";
import { ProjectProfitabilitySection } from "@sale_project/components/project_right_side_panel/components/project_profitability_section";

patch(ProjectProfitability, {
    components: {
        ...ProjectProfitability.components,
        ProjectProfitabilitySection,
    },
});
Object.assign(projectProfitabilityProps, {
    projectId: Number,
    context: Object,
});
