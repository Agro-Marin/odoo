/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

export class SurveyResultSegments extends Interaction {
    static selector = ".o_survey_segment_charts";

    setup() {
        this.charts = [];
        this.loadSegments();
    }

    async loadSegments() {
        const surveyId = parseInt(this.el.dataset.surveyId);
        const data = await rpc(`/survey/results/${surveyId}/segments`);
        if (!data.total) {
            return;
        }
        this.renderDoughnut(
            this.el.querySelector(".o_survey_segment_score_canvas"),
            data.score_bands,
            ["#dc3545", "#ffc107", "#17a2b8", "#28a745"]
        );
        this.renderDoughnut(
            this.el.querySelector(".o_survey_segment_quality_canvas"),
            data.quality_tiers,
            ["#dc3545", "#ffc107", "#28a745"]
        );
        if (data.duration_buckets.length) {
            this.renderDoughnut(
                this.el.querySelector(".o_survey_segment_duration_canvas"),
                data.duration_buckets,
                ["#6f42c1", "#0d6efd", "#20c997", "#fd7e14"]
            );
        }
    }

    renderDoughnut(canvas, segments, colors) {
        if (!canvas || !segments.length) {
            return;
        }
        // eslint-disable-next-line no-undef
        const chart = new Chart(canvas, {
            type: "doughnut",
            data: {
                labels: segments.map((s) => s.label),
                datasets: [{
                    data: segments.map((s) => s.count),
                    backgroundColor: colors,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 12 } },
                },
            },
        });
        this.charts.push(chart);
    }

    destroy() {
        for (const chart of this.charts) {
            chart.destroy();
        }
        super.destroy();
    }
}

registry.category("public.interactions").add("survey.result_segments", SurveyResultSegments);
