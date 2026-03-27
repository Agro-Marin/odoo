import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

export class SurveyResultComparison extends Interaction {
    static selector = ".o_survey_comparison_form";

    dynamicContent = {
        ".o_survey_compare_btn": { "t-on-click": this.onCompareClick },
    };

    async onCompareClick() {
        const surveyId = parseInt(this.el.dataset.surveyId);
        const data = await rpc(`/survey/results/${surveyId}/compare`, {
            period_a_from: this.el.querySelector(".o_compare_a_from").value,
            period_a_to: this.el.querySelector(".o_compare_a_to").value,
            period_b_from: this.el.querySelector(".o_compare_b_from").value,
            period_b_to: this.el.querySelector(".o_compare_b_to").value,
        });
        this.renderResults(data);
    }

    renderResults(data) {
        const container = this.el.closest(".o_survey_comparison")
            .querySelector(".o_survey_comparison_results");

        const delta = (val) => {
            if (val === null || val === undefined) return "";
            const sign = val > 0 ? "+" : "";
            const color = val > 0 ? "text-success" : val < 0 ? "text-danger" : "text-muted";
            return `<span class="${color} fw-bold">${sign}${val}</span>`;
        };

        const rows = [
            ["Responses", data.period_a.count, data.period_b.count, data.deltas.count],
            ["Avg Score (%)", data.period_a.avg_score, data.period_b.avg_score, data.deltas.avg_score],
            ["Avg Quality", data.period_a.avg_quality, data.period_b.avg_quality, data.deltas.avg_quality],
        ];
        if (data.period_a.success_rate !== null) {
            rows.push(["Success Rate (%)", data.period_a.success_rate, data.period_b.success_rate, data.deltas.success_rate]);
        }

        container.innerHTML = `
            <table class="table table-sm table-bordered">
                <thead class="table-light">
                    <tr><th>Metric</th><th>Period A</th><th>Period B</th><th>Delta</th></tr>
                </thead>
                <tbody>
                    ${rows.map(([label, a, b, d]) => `
                        <tr><td>${label}</td><td>${a}</td><td>${b}</td><td>${delta(d)}</td></tr>
                    `).join("")}
                </tbody>
            </table>
        `;
    }
}

registry.category("public.interactions").add("survey.result_comparison", SurveyResultComparison);
