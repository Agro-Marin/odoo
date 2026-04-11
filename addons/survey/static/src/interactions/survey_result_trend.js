/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

export class SurveyResultTrend extends Interaction {
    static selector = ".o_survey_trend_chart_container";

    dynamicContent = {
        ".o_survey_trend_granularity": { "t-on-change": this.onGranularityChange },
    };

    setup() {
        this.surveyId = parseInt(this.el.dataset.surveyId);
        this.chart = null;
        this.loadTrends("day");
    }

    async onGranularityChange(ev) {
        await this.loadTrends(ev.target.value);
    }

    async loadTrends(granularity) {
        const data = await rpc(`/survey/results/${this.surveyId}/trends`, { granularity });
        this.renderChart(data);
    }

    renderChart(data) {
        if (this.chart) {
            this.chart.destroy();
        }
        const canvas = this.el.querySelector(".o_survey_trend_canvas");
        if (!canvas) {
            return;
        }

        const datasets = [
            {
                label: "Responses",
                data: data.counts,
                borderColor: "#714B67",
                backgroundColor: "rgba(113, 75, 103, 0.1)",
                fill: true,
                yAxisID: "y",
                tension: 0.3,
            },
        ];

        const scales = {
            y: {
                type: "linear",
                position: "left",
                title: { display: true, text: "Responses" },
                beginAtZero: true,
            },
        };

        if (data.avg_scores && data.avg_scores.length) {
            datasets.push({
                label: "Avg Score (%)",
                data: data.avg_scores,
                borderColor: "#28a745",
                backgroundColor: "rgba(40, 167, 69, 0.1)",
                fill: false,
                yAxisID: "y1",
                tension: 0.3,
                borderDash: [5, 5],
            });
            scales.y1 = {
                type: "linear",
                position: "right",
                title: { display: true, text: "Avg Score (%)" },
                min: 0,
                max: 100,
                grid: { drawOnChartArea: false },
            };
        }

        // eslint-disable-next-line no-undef
        this.chart = new Chart(canvas, {
            type: "line",
            data: { labels: data.labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales,
                plugins: {
                    legend: { position: "top" },
                },
            },
        });
    }

    destroy() {
        if (this.chart) {
            this.chart.destroy();
        }
        super.destroy();
    }
}

registry.category("public.interactions").add("survey.result_trend", SurveyResultTrend);
