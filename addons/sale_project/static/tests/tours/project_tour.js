import { registry } from "@web/core/registry";
import "@project/../tests/tours/project_tour";
import { patch } from "@web/core/utils/patch";

patch(registry.category("web_tour.tours").get("project_test_tour"), {
    steps() {
        const originalSteps = super.steps();
        const projectCreationStepIndex = originalSteps.findIndex(
            (step) => step.id === "project_creation",
        );
        originalSteps.splice(projectCreationStepIndex, 0, {
            trigger: "div[name='allow_billable'] input",
            run: "edit Test",
        });

        return originalSteps;
    },
});
