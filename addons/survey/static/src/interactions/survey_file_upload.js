/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Interaction } from "@web/public/interaction";

export class SurveyFileUpload extends Interaction {
    static selector = ".o_survey_file_upload";

    dynamicContent = {
        ".o_survey_file_input": {
            "t-on-change": this.onFileSelected,
        },
        ".o_survey_file_feedback": {
            "t-out": () => this.feedback,
            "t-att-class": () => ({
                "text-danger": this.failed,
                "text-success": !this.failed && !!this.feedback,
            }),
        },
    };

    setup() {
        this.feedback = "";
        this.failed = false;
        const formEl = this.el.closest("form");
        this.surveyToken = formEl?.dataset.surveyToken;
        this.answerToken = formEl?.dataset.answerToken;
    }

    /**
     * The file is uploaded as soon as it is chosen, and only the resulting
     * attachment id travels with the answer. Submitting the bytes alongside the
     * rest of the page would mean the whole JSON-RPC payload carries them, and
     * a failed upload would fail the page rather than the question.
     */
    async onFileSelected(ev) {
        const file = ev.currentTarget.files?.[0];
        delete this.el.dataset.attachmentId;
        if (!file) {
            this.feedback = "";
            this.failed = false;
            return;
        }
        const formData = new FormData();
        formData.append("file", file);
        formData.append("question_id", this.el.dataset.name);
        formData.append("csrf_token", odoo.csrf_token);

        this.feedback = _t("Uploading…");
        this.failed = false;
        try {
            const response = await this.waitFor(
                fetch(`/survey/upload/${this.surveyToken}/${this.answerToken}`, {
                    method: "POST",
                    body: formData,
                }),
            );
            const result = await this.waitFor(response.json());
            if (!response.ok || result.error) {
                this.failed = true;
                this.feedback = result.message || _t("Upload failed.");
                ev.currentTarget.value = "";
                return;
            }
            this.el.dataset.attachmentId = result.attachment_id;
            this.feedback = result.name;
        } catch {
            this.failed = true;
            this.feedback = _t("Upload failed.");
            ev.currentTarget.value = "";
        }
    }
}

registry
    .category("public.interactions")
    .add("survey.survey_file_upload", SurveyFileUpload);
