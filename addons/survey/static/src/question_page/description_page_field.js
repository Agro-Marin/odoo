/** @odoo-module native */
import { useRef } from "@odoo/owl";
import { useSurveyContext } from "@survey/survey_context";
import { registry } from "@web/core/registry";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { CharField, charField } from "@web/fields/basic/char/char_field";

class DescriptionPageField extends CharField {
    static template = "survey.DescriptionPageField";
    setup() {
        super.setup();
        this.surveyContext = useSurveyContext();
        const inputRef = useRef("input");
        useLayoutEffect(
            (input) => {
                if (input) {
                    input.classList.add("col");
                }
            },
            () => [inputRef.el],
        );
    }
    onExternalBtnClick() {
        this.surveyContext.openRecord(this.props.record);
    }
}

registry.category("fields").add("survey_description_page", {
    ...charField,
    component: DescriptionPageField,
});
