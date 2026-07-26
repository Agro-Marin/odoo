/** @odoo-module native */
import { registry } from "@web/core/registry";
import { resizeTextArea } from "@web/core/utils/dom/autoresize";
import { Interaction } from "@web/public/interaction";

export class SurveyPrint extends Interaction {
    static selector = ".o_survey_print";

    dynamicContent = {
        ".o_survey_user_results_print": { "t-on-click": this.onPrintUserResultsClick },
    };

    start() {
        // Will allow the textarea to resize if any carriage return instead of showing scrollbar.
        document.querySelectorAll("textarea").forEach((textarea) => {
            resizeTextArea(textarea);
        });
    }

    onPrintUserResultsClick() {
        window.print();
    }
}

registry.category("public.interactions").add("survey.survey_print", SurveyPrint);
