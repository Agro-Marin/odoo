import { expect, test } from "@odoo/hoot";
import { SurveyResultChart } from "@survey/interactions/survey_result_chart";
import { SurveySessionChart } from "@survey/interactions/survey_session_chart";

test("result charts preserve their colors after a full palette cycle", () => {
    const chart = Object.assign(Object.create(SurveyResultChart.prototype), {
        graphData: Array.from({ length: 21 }, (_, index) => ({
            key: `Group ${index}`,
            values: [{ text: "Answer", count: 1 }],
        })),
        rightAnswers: [],
    });
    const { datasets } = chart.getMultibarChartConfig().data;
    expect(datasets[0].backgroundColor).toBe("#1f77b4");
    expect(datasets[10].backgroundColor).toBe("#8c564b");
    expect(datasets[19].backgroundColor).toBe("#9edae5");
    expect(datasets[20].backgroundColor).toBe("#1f77b4");
});

test("session charts preserve RGB colors and wrong-answer opacity", () => {
    const chart = Object.assign(Object.create(SurveySessionChart.prototype), {
        showAnswers: false,
        hasCorrectAnswers: true,
        isValidAnswer: () => false,
    });
    expect(chart.getBackgroundColor({ dataIndex: 10 })).toBe("rgba(140,86,75,0.8)");
    expect(chart.getBackgroundColor({ dataIndex: 20 })).toBe("rgba(31,119,180,0.8)");
    chart.showAnswers = true;
    expect(chart.getBackgroundColor({ dataIndex: 20 })).toBe("rgba(31,119,180,0.2)");
});
