/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class SurveyConstantSum extends Interaction {
    static selector = ".o_survey_constant_sum";

    dynamicContent = {
        "input[data-answer-id]": {
            "t-on-input": this.onValueInput,
        },
        ".o_survey_constant_sum_total": {
            "t-out": () => String(this.total),
            "t-att-class": () => ({
                "text-danger": this.total !== this.target,
                "text-success": this.total === this.target,
            }),
        },
    };

    setup() {
        this.target = Number(this.el.dataset.total);
        this.total = 0;
    }

    start() {
        this.recompute();
    }

    /**
     * The server rejects a submission whose values do not sum to the target, so
     * the running total has to be visible while the respondent types. Without
     * it the only feedback is a validation error after submit, on a question
     * whose whole point is arithmetic.
     */
    recompute() {
        let total = 0;
        for (const inputEl of this.el.querySelectorAll("input[data-answer-id]")) {
            total += Number(inputEl.value) || 0;
        }
        this.total = total;
    }

    onValueInput() {
        this.recompute();
    }
}

registry
    .category("public.interactions")
    .add("survey.survey_constant_sum", SurveyConstantSum);
