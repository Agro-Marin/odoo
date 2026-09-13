/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { selectElements } from "@html_editor/utils/dom_traversal";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { session } from "@web/session";

import { FormActionFieldsOption } from "./form_action_fields_option.js";
import { getModelName, getParsedDataFor } from "./utils.js";

const log = makeLogger("website.builder.option.form_option");

export class FormOption extends BaseOptionComponent {
    static template = "website.s_website_form_form_option";
    static dependencies = ["websiteFormOption"];
    static selector = ".s_website_form";
    static applyTo = "form";
    static components = { FormActionFieldsOption };
    static async cleanForSave(el, { dependencies, services }) {
        for (const sigEl of el.querySelectorAll("input[name=website_form_signature]")) {
            sigEl.remove();
        }

        for (const formEl of selectElements(
            el,
            ".s_website_form form[data-model_name]",
        )) {
            const model = formEl.dataset.model_name;
            const endAuthorizedFields = log.perf(
                "cleanForSave authorized fields",
                () => ({
                    model,
                }),
            );
            const authorizedFields =
                await dependencies.websiteFormOption.fetchAuthorizedFields(formEl);
            endAuthorizedFields();
            const fields = [
                ...formEl.querySelectorAll(
                    ".s_website_form_field:not(.s_website_form_custom) .s_website_form_input",
                ),
            ]
                .map((el) => el.name)
                .filter((name) => !authorizedFields[name]?._property);
            log.logic("cleanForSave formbuilder_whitelist", () => ({
                model,
                fields: fields.length,
                whitelist: !!fields.length,
            }));
            if (fields.length) {
                services.orm.call("ir.model.fields", "formbuilder_whitelist", [
                    model,
                    [...new Set(fields)],
                ]);
            }
        }
    }

    setup() {
        super.setup();
        useLifecycleLog(log);
        const { prepareFormModel, applyFormModel, fetchModels } =
            this.dependencies.websiteFormOption;
        this.hasRecaptchaKey = !!session.recaptcha_public_key;

        const el = this.env.getEditingElement();
        this.messageEl = el.parentElement.querySelector(".s_website_form_end_message");
        this.showEndMessage = false;
        const formId = el.id;
        const dataForValues = getParsedDataFor(formId, el.ownerDocument);
        if (dataForValues) {
            this.dataForEmailTo = dataForValues["email_to"];
        }
        this.state = useDomState(async (el) => {
            const modelName = getModelName(el);

            this.modelCantChange = !!el.getAttribute("hide-change-model");

            const models = await fetchModels(el);
            const activeForm = models.find((m) => m.model === modelName);

            if (!el.dataset.model_name) {
                const endInitModel = log.perf("domState init form model", () => ({
                    model: activeForm?.model,
                }));
                const formInfo = await prepareFormModel(el, activeForm);
                applyFormModel(el, activeForm, activeForm.id, formInfo);
                endInitModel();
            }
            return {
                models,
                activeForm,
            };
        });
    }
}
