/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { SyncCache } from "@html_builder/utils/sync_cache";
import { isSmallInteger } from "@html_builder/utils/utils";
import { Plugin } from "@html_editor/plugin";
import { selectElements } from "@html_editor/utils/dom_traversal";
import { reactive } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { formatDate } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Cache } from "@web/core/utils/collections/cache";
import { renderToElement } from "@web/core/utils/render";
import { redirect } from "@web/core/utils/urls";
import { ConfirmationDialog } from "@web/ui/dialog";

import { FormFieldOptionRedraw } from "./form_field_option_redraw.js";
import { FormOption } from "./form_option.js";
import { FormOptionAddFieldButton } from "./form_option_add_field_button.js";
import {
    deleteConditionalVisibility,
    findCircular,
    getActiveField,
    getCustomField,
    getDefaultFormat,
    getDependencyEl,
    getDomain,
    getFieldFormat,
    getFieldName,
    getFieldType,
    getLabelPosition,
    getMark,
    getModelName,
    getMultipleInputs,
    getNewRecordId,
    getParsedDataFor,
    getQuotesEncodedName,
    getSelect,
    isFieldCustom,
    isOptionalMark,
    isRequiredMark,
    renderField,
    replaceFieldElement,
    rerenderField,
    setActiveProperties,
    setVisibilityDependency,
} from "./utils.js";

/**
 * @typedef { Object } FormOptionShared
 * @property { FormOptionPlugin['prepareFormModel'] } prepareFormModel
 * @property { FormOptionPlugin['getModelsCache'] } getModelsCache
 * @property { FormOptionPlugin['applyFormModel'] } applyFormModel
 * @property { FormOptionPlugin['addHiddenField'] } addHiddenField
 * @property { FormOptionPlugin['fetchAuthorizedFields'] } fetchAuthorizedFields
 * @property { FormOptionPlugin['loadFieldOptionData'] } loadFieldOptionData
 * @property { FormOptionPlugin['prepareFields'] } prepareFields
 * @property { FormOptionPlugin['replaceField'] } replaceField
 * @property { FormOptionPlugin['prepareConditionInputs'] } prepareConditionInputs
 * @property { FormOptionPlugin['setLabelsMark'] } setLabelsMark
 * @property { FormOptionPlugin['clearValidationDataset'] } clearValidationDataset
 * @property { FormOptionPlugin['defaultMessage'] } defaultMessage
 * @property { FormOptionPlugin['fetchModels'] } fetchModels
 */

const { DateTime } = luxon;

const log = makeLogger("website.builder.plugin.website_form_option");

export class WebsiteFormSubmitOption extends BaseOptionComponent {
    static template = "website.s_website_form_submit_option";
    static selector = ".s_website_form_submit";
    static exclude = ".s_website_form_no_submit_options";
}

const DEFAULT_EMAIL_TO_VALUE = "info@yourcompany.example.com";
export class FormOptionPlugin extends Plugin {
    static id = "websiteFormOption";
    static dependencies = ["builderActions", "builderOptions", "savePlugin"];
    static shared = [
        "prepareFormModel",
        "getModelsCache",
        "applyFormModel",
        "addHiddenField",
        "fetchAuthorizedFields",
        "loadFieldOptionData",
        "prepareFields",
        "replaceField",
        "prepareConditionInputs",
        "setLabelsMark",
        "clearValidationDataset",
        "defaultMessage",
        "fetchModels",
    ];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_header_middle_buttons: [
            {
                Component: FormOptionAddFieldButton,
                selector: ".s_website_form",
                applyTo: "form",
                props: {
                    addField: (formEl) => this.addFieldToForm(formEl),
                    tooltip: _t("Add a new field at the end"),
                },
            },
            {
                Component: FormOptionAddFieldButton,
                selector: ".s_website_form_field",
                exclude: ".s_website_form_dnone",
                props: {
                    addField: (fieldEl) => this.addFieldAfterField(fieldEl),
                    tooltip: _t("Add a new field after this one"),
                },
            },
        ],
        clone_disabled_reason_providers: ({ el, reasons }) => {
            if (
                el.classList.contains("s_website_form_field") &&
                !el.classList.contains("s_website_form_custom")
            ) {
                reasons.push(_t("You cannot duplicate this field."));
            }
        },
        remove_disabled_reason_providers: ({ el, reasons }) => {
            if (el.classList.contains("s_website_form_model_required")) {
                reasons.push(
                    _t(
                        "This field is mandatory for this action. You cannot remove it. Try hiding it with the 'Visibility' option instead and add it a default value.",
                    ),
                );
            }
        },
        builder_options: [FormOption, FormFieldOptionRedraw, WebsiteFormSubmitOption],
        builder_actions: {
            SelectAction,
            AddActionFieldAction,
            PromptSaveRedirectAction,
            UpdateLabelsMarkAction,
            SetMarkAction,
            OnSuccessAction,
            ToggleEndMessageAction,
            FormToggleRecaptchaLegalAction,
            CustomFieldAction,
            ExistingFieldAction,
            SelectTypeAction,
            ExistingFieldSelectTypeAction,
            MultiCheckboxDisplayAction,
            SetLabelTextAction,
            SelectLabelPositionAction,
            ToggleDescriptionAction,
            SelectTextareaValueAction,
            ToggleRequiredAction,
            SetVisibilityAction,
            SetVisibilityDependencyAction,
            SetFormCustomFieldValueListAction,
            PropertyAction,
            SetCustomErrorMessageAction,
            SetDefaultErrorMessageAction,
            SetRequirementComparatorAction,
            SetMultipleFilesAction,
        },
        content_not_editable_selectors: ".s_website_form form",
        content_editable_selectors: [
            ".s_website_form_send",
            ".s_website_form_field_description",
            ".s_website_form_recaptcha",
            ".row > div:not(.s_website_form_field, .s_website_form_submit, .s_website_form_field *, .s_website_form_submit *)",
        ].map((selector) => `.s_website_form form ${selector}`),
        clean_for_save_handlers: ({ root: rootEl }) => {
            this.removeSuccessMessagePreviews(rootEl);
        },
        dropzone_selector: [
            {
                selector: ".s_website_form",
                excludeAncestor: "form",
            },
            {
                selector: ".s_website_form_field, .s_website_form_submit",
                exclude: ".s_website_form_dnone",
                dropNear: ".s_website_form_field",
                dropLockWithin: "form",
            },
        ],
        so_content_addition_selector: [".s_website_form"],
        on_snippet_dropped_handlers: this.onSnippetDropped.bind(this),
        on_cloned_handlers: this.onCloned.bind(this),
        is_unremovable_selector: ".s_website_form_send, .s_website_form_submit",
    };
    setup() {
        log.lifecycle("setup");
        this.modelsCache = new SyncCache(this._fetchModels.bind(this));
        this.fieldRecordsCache = new SyncCache(this._fetchFieldRecords.bind(this));
        this.authorizedFieldsCache = new Cache(
            this._fetchAuthorizedFields.bind(this),
            ({ cacheKey }) => cacheKey,
        );
        this.visibilityConditionCachedRecords = new Cache(
            this._getVisibilityConditionCachedRecords.bind(this),
            JSON.stringify,
        );
    }
    destroy() {
        super.destroy();
        log.lifecycle("destroy");
        this.modelsCache.invalidate();
        this.fieldRecordsCache.invalidate();
        this.authorizedFieldsCache.invalidate();
        this.visibilityConditionCachedRecords.invalidate();
    }
    getModelsCache(formEl) {
        return this.modelsCache.get();
    }
    async fetchModels(formEl) {
        return this.modelsCache.preload();
    }
    async _fetchModels() {
        log.pipeline("modelsCache miss: rpc get_compatible_form_models");
        return await this.services.orm.call("ir.model", "get_compatible_form_models");
    }
    async fetchFieldRecords(field) {
        if (field) {
            field.records = await this.fieldRecordsCache.preload(field);
            return field.records;
        }
    }
    /**
     * @param {Object} field
     * @returns {Promise<Object>}
     */
    async _fetchFieldRecords(field) {
        if (!field) {
            return;
        }
        field.required = field.required ? 1 : null;

        if (field.records) {
            log.logic("_fetchFieldRecords: records already present", () => ({
                name: field.name,
                records: field.records.length,
            }));
            return field.records;
        }
        if (field._property && field.type === "tags") {
            field.records = field.tags.map((tag) => ({
                id: tag[0].replaceAll("\\", "\\/").replaceAll(",", "\\,"),
                display_name: tag[1],
            }));
        } else if (field._property && field.comodel) {
            const endSearchComodel = log.perf(
                "_fetchFieldRecords property comodel",
                () => ({
                    name: field.name,
                    comodel: field.comodel,
                }),
            );
            field.records = await this.services.orm.searchRead(
                field.comodel,
                field.domain || [],
                ["display_name"],
            );
            endSearchComodel(() => ({ records: field.records.length }));
        } else if (field.type === "selection") {
            field.records = field.selection.map((el) => ({
                id: el[0],
                display_name: el[1],
            }));
        } else if (field.relation && field.relation !== "ir.attachment") {
            const fieldNames = field.fieldName ? [field.fieldName] : ["display_name"];
            const endSearchRelation = log.perf("_fetchFieldRecords relation", () => ({
                name: field.name,
                relation: field.relation,
            }));
            field.records = await this.services.orm.searchRead(
                field.relation,
                field.domain || [],
                fieldNames,
            );
            endSearchRelation(() => ({ records: field.records.length }));
            if (field.fieldName) {
                field.records.forEach((r) => (r["display_name"] = r[field.fieldName]));
            }
        }
        return field.records;
    }
    async prepareFormModel(el, activeForm) {
        const formKey = activeForm?.website_form_key;
        const formInfo = registry
            .category("website.form_editor_actions")
            .get(formKey, null);
        log.logic("prepareFormModel", () => ({
            formKey,
            model: activeForm?.model,
            hasFormInfo: !!formInfo,
        }));
        if (formInfo) {
            const formatInfo = getDefaultFormat(el);
            const endFetchRecords = log.perf(
                "prepareFormModel fetch field records",
                () => ({
                    formKey,
                    formFields: formInfo.formFields.length,
                    fields: formInfo.fields?.length,
                }),
            );
            await Promise.all(
                formInfo.formFields.map((field) => {
                    field.formatInfo = formatInfo;
                    return this.fetchFieldRecords(field);
                }),
            );
            await this.fetchFormInfoFields(formInfo);
            endFetchRecords();
        }
        return formInfo;
    }
    /**
     * @param {HTMLElement} el
     * @param {string} value
     * @param {string} fieldName
     */
    addHiddenField(el, value, fieldName) {
        for (const hiddenEl of el.querySelectorAll(
            `.s_website_form_dnone:has(input[name="${CSS.escape(fieldName)}"])`,
        )) {
            hiddenEl.remove();
        }
        if (fieldName === "email_to" && !value && !this.dataForEmailTo) {
            log.logic("addHiddenField: email_to falls back to default", () => ({
                value: DEFAULT_EMAIL_TO_VALUE,
            }));
            value = DEFAULT_EMAIL_TO_VALUE;
        }
        log.logic("addHiddenField", () => ({
            fieldName,
            value,
            rendered: !!(value || fieldName === "email_to"),
        }));
        if (value || fieldName === "email_to") {
            const hiddenField = renderToElement("website.form_field_hidden", {
                field: {
                    name: fieldName,
                    value: value,
                    dnone: true,
                    formatInfo: {},
                },
            });
            el.querySelector(".s_website_form_submit").insertAdjacentElement(
                "beforebegin",
                hiddenField,
            );
        }
    }
    /**
     * @param {HTMLElement} el
     * @param {Object} activeForm
     * @param {Integer} modelId
     * @param {Object} formInfo
     */
    applyFormModel(el, activeForm, modelId, formInfo) {
        log.pipeline("applyFormModel", () => ({
            modelId,
            model: activeForm?.model,
            formFields: formInfo?.formFields.length,
            hiddenFields: formInfo?.fields?.length,
        }));
        let oldFormInfo;
        if (modelId) {
            const oldFormKey = activeForm.website_form_key;
            if (oldFormKey) {
                oldFormInfo = registry
                    .category("website.form_editor_actions")
                    .get(oldFormKey, null);
            }
            for (const fieldEl of el.querySelectorAll(".s_website_form_field")) {
                fieldEl.remove();
            }
            activeForm = this.getModelsCache(el).find((model) => model.id === modelId);
        }
        if (!el.dataset.successMode) {
            el.dataset.successMode = "redirect";
        }
        if (el.dataset.successMode === "redirect") {
            const currentSuccessPage = el.dataset.successPage;
            if (formInfo && formInfo.successPage) {
                el.dataset.successPage = formInfo.successPage;
            } else if (
                !oldFormInfo ||
                (oldFormInfo !== formInfo &&
                    oldFormInfo.successPage &&
                    currentSuccessPage === oldFormInfo.successPage)
            ) {
                log.logic("applyFormModel: reset success page to default", () => ({
                    currentSuccessPage,
                    oldSuccessPage: oldFormInfo?.successPage,
                }));
                el.dataset.successPage = "/contactus-thank-you";
            }
        }
        el.dataset.model_name = activeForm.model;
        if (formInfo) {
            const formatInfo = getDefaultFormat(el);
            formInfo.formFields.forEach((field) => {
                const _field = { ...field };
                _field.formatInfo = formatInfo;
                const locationEl = el.querySelector(
                    ".s_website_form_submit, .s_website_form_recaptcha",
                );
                locationEl.insertAdjacentElement("beforebegin", renderField(_field));
            });
            formInfo.fields?.forEach((field) => {
                if (field.defaultValue) {
                    this.addHiddenField(el, field.defaultValue, field.name);
                }
            });
        }
    }
    async fetchFormInfoFields(formInfo) {
        if (formInfo.fields) {
            const proms = formInfo.fields.map((field) => this.fetchFieldRecords(field));
            await Promise.all(proms);
        }
    }
    async fetchAuthorizedFields(formEl) {
        const model = getModelName(formEl);
        const propertyOrigins = {};
        const parts = [model];
        for (const hiddenInputEl of [
            ...formEl.querySelectorAll("input[type=hidden]"),
        ].sort((firstEl, secondEl) => firstEl.name.localeCompare(secondEl.name))) {
            parts.push(hiddenInputEl.name);
            parts.push(hiddenInputEl.value);
            propertyOrigins[hiddenInputEl.name] = hiddenInputEl.value;
        }
        const cacheKey = parts.join("/");
        log.pipeline("fetchAuthorizedFields", () => ({ cacheKey }));
        return this.authorizedFieldsCache.read({ cacheKey, model, propertyOrigins });
    }
    async _fetchAuthorizedFields({ cacheKey, model, propertyOrigins }) {
        log.pipeline("authorizedFieldsCache miss: rpc get_fields_authorized", () => ({
            cacheKey,
        }));
        return this.services.orm.call("ir.model", "get_fields_authorized", [
            model,
            propertyOrigins,
        ]);
    }
    async _getVisibilityConditionCachedRecords(model, domain, fields, kwargs = {}) {
        log.pipeline("visibilityConditionCachedRecords miss: searchRead", () => ({
            model,
            fields,
        }));
        return this.services.orm.searchRead(model, domain, fields, {
            ...kwargs,
            limit: 1000,
        });
    }

    setLabelsMark(formEl) {
        formEl.querySelectorAll(".s_website_form_mark").forEach((el) => el.remove());
        const mark = getMark(formEl);
        if (!mark) {
            log.logic("setLabelsMark: no mark, labels cleared only");
            return;
        }
        let fieldsToMark = [];
        const requiredSelector =
            ".s_website_form_model_required, .s_website_form_required";
        const fields = Array.from(formEl.querySelectorAll(".s_website_form_field"));
        if (isRequiredMark(formEl)) {
            fieldsToMark = fields.filter((el) => el.matches(requiredSelector));
        } else if (isOptionalMark(formEl)) {
            fieldsToMark = fields.filter((el) => !el.matches(requiredSelector));
        }
        log.pipeline("setLabelsMark", () => ({
            mark,
            fields: fields.length,
            marked: fieldsToMark.length,
        }));
        fieldsToMark.forEach((field) => {
            const span = document.createElement("span");
            span.classList.add("s_website_form_mark");
            span.textContent = ` ${mark}`;
            field.querySelector(".s_website_form_label").appendChild(span);
        });
    }
    addFieldToForm(formEl) {
        const field = getCustomField("char", _t("Custom Text"));
        field.formatInfo = getDefaultFormat(formEl);
        const fieldEl = renderField(field);
        let locationEl = formEl.querySelector(
            ".s_website_form_submit, .s_website_form_recaptcha",
        );
        log.logic("addFieldToForm", () => ({ hasSubmitOrRecaptcha: !!locationEl }));
        if (!locationEl) {
            locationEl = formEl.querySelector(".s_website_form_rows");
            locationEl.insertAdjacentElement("beforeend", fieldEl);
        } else {
            locationEl.insertAdjacentElement("beforebegin", fieldEl);
        }
        this.dependencies.builderOptions.setNextTarget(fieldEl);
    }
    addFieldAfterField(fieldEl) {
        const formEl = fieldEl.closest("form");
        const field = getCustomField("char", _t("Custom Text"));
        field.formatInfo = getFieldFormat(fieldEl);
        field.formatInfo.requiredMark = isRequiredMark(formEl);
        field.formatInfo.optionalMark = isOptionalMark(formEl);
        field.formatInfo.mark = getMark(formEl);
        const newFieldEl = renderField(field);
        log.pipeline("addFieldAfterField", () => ({ type: field.type }));
        fieldEl.insertAdjacentElement("afterend", newFieldEl);
        this.dependencies.builderOptions.setNextTarget(newFieldEl);
    }
    async prepareFields({ editingElement: fieldEl, value }) {
        const endPrepareFields = log.perf("prepareFields", () => ({ value }));
        const fieldOptionData = await this.loadFieldOptionData(fieldEl);
        const fieldName = getFieldName(fieldEl);
        const field = fieldOptionData.fields[fieldName];
        await this.fetchFieldRecords(field);
        if (fieldOptionData.fields[value]) {
            await this.fetchFieldRecords(fieldOptionData.fields[value]);
        }
        endPrepareFields();
        return fieldOptionData.fields;
    }
    async prepareConditionInputs({ editingElement: fieldEl, value }) {
        const endPrepareConditionInputs = log.perf("prepareConditionInputs", () => ({
            value,
        }));
        const fieldOptionData = await this.loadFieldOptionData(fieldEl);
        const fieldName = getFieldName(fieldEl);
        const field = fieldOptionData.fields[fieldName];
        await this.fetchFieldRecords(field);
        if (fieldOptionData.fields[value]) {
            await this.fetchFieldRecords(fieldOptionData.fields[value]);
        }
        endPrepareConditionInputs(() => ({
            conditionInputs: fieldOptionData.conditionInputs.length,
        }));
        return fieldOptionData.conditionInputs;
    }
    /**
     * @param {HTMLElement} oldFieldEl
     * @param {Object} field
     * @param {Array} fields
     * @returns {Promise}
     */
    replaceField(oldFieldEl, field, fields) {
        const activeField = getActiveField(oldFieldEl, { fields });
        log.logic("replaceField", () => ({
            from: activeField.type,
            to: field.type,
            name: field.name,
            resetValue: activeField.type !== field.type,
        }));
        if (activeField.type !== field.type) {
            field.value = "";
        }
        const targetEl = oldFieldEl.querySelector(".s_website_form_input");
        if (targetEl) {
            if (["checkbox", "radio"].includes(targetEl.getAttribute("type"))) {
                field.id = targetEl.id.slice(0, -1);
            } else {
                field.id = targetEl.id;
            }
        }

        const newValuesText = field.records
            ? field.records.map((record) => record.id)
            : [];
        const inputEls = oldFieldEl.querySelectorAll(".s_website_form_input, option");
        const inputName = oldFieldEl.querySelector(".s_website_form_input")?.name;
        const formEl = oldFieldEl.closest(".s_website_form");
        for (let i = 0; i < inputEls.length; i++) {
            const input = inputEls[i];
            if (
                newValuesText[i] &&
                input.value &&
                !newValuesText.includes(input.value)
            ) {
                log.logic("replaceField: remap visibility conditions", () => ({
                    index: i,
                    from: input.value,
                    to: newValuesText[i],
                }));
                for (const dependentEl of formEl.querySelectorAll(
                    `[data-visibility-condition="${CSS.escape(
                        input.value,
                    )}"][data-visibility-dependency="${CSS.escape(inputName)}"]`,
                )) {
                    dependentEl.dataset.visibilityCondition = newValuesText[i];
                }
                break;
            }
        }

        const fieldEl = renderField(field);
        replaceFieldElement(oldFieldEl, fieldEl);
    }
    async loadFieldOptionData(fieldEl) {
        const formEl = fieldEl.closest("form");
        const fields = {};
        const endAuthorizedFields = log.perf(
            "loadFieldOptionData authorized fields",
            () => ({
                model: formEl.dataset.model_name,
            }),
        );
        const existingFields = await this.fetchAuthorizedFields(formEl).then(
            (fieldsFromCache) => {
                for (const [fieldName, field] of Object.entries(fieldsFromCache)) {
                    field.name = fieldName;
                    const fieldDomain = getDomain(
                        formEl,
                        field.name,
                        field.type,
                        field.relation,
                    );
                    field.domain = fieldDomain || field.domain || [];
                    fields[fieldName] = field;
                }
                return Object.keys(fieldsFromCache)
                    .map((key) => {
                        const field = fieldsFromCache[key];
                        return {
                            name: field.name,
                            string: field.string,
                        };
                    })
                    .sort((a, b) =>
                        a.string.localeCompare(b.string, undefined, {
                            numeric: true,
                            sensitivity: "base",
                        }),
                    );
            },
        );
        endAuthorizedFields(() => ({ existingFields: existingFields.length }));
        const existingDependencyNames = [];
        const conditionInputs = [];
        for (const el of formEl.querySelectorAll(
            ".s_website_form_field:not(.s_website_form_dnone), .s_website_form_field[data-type]",
        )) {
            const inputEl = el.querySelector(".s_website_form_input");
            if (
                el.querySelector(".s_website_form_label_content") &&
                inputEl &&
                inputEl.name &&
                inputEl.name !== fieldEl.querySelector(".s_website_form_input").name &&
                !existingDependencyNames.includes(inputEl.name) &&
                !findCircular(el, fieldEl)
            ) {
                conditionInputs.push({
                    name: inputEl.name,
                    textContent: el.querySelector(".s_website_form_label_content")
                        .textContent,
                });
                existingDependencyNames.push(inputEl.name);
            }
        }

        const comparator = fieldEl.dataset.visibilityComparator;
        const dependencyEl = getDependencyEl(fieldEl);
        const conditionValueList = [];
        if (dependencyEl) {
            const containerEl = dependencyEl.closest(".s_website_form_field");
            const fieldType = containerEl?.dataset.type;
            if (
                ["radio", "checkbox"].includes(dependencyEl.type) ||
                dependencyEl.nodeName === "SELECT" ||
                fieldType === "record"
            ) {
                const inputContainerEl = fieldEl;
                if (dependencyEl.nodeName === "SELECT") {
                    for (const option of dependencyEl.querySelectorAll("option")) {
                        conditionValueList.push({
                            value: option.value,
                            textContent: option.textContent || `<${_t("no value")}>`,
                        });
                    }
                    if (!inputContainerEl.dataset.visibilityCondition) {
                        inputContainerEl.dataset.visibilityCondition =
                            dependencyEl.querySelector("option").value;
                    }
                } else if (fieldType === "record") {
                    const model = containerEl.dataset.model;
                    const idField = containerEl.dataset.idField || "id";
                    const displayNameField =
                        containerEl.dataset.displayNameField || "display_name";
                    const endConditionRecords = log.perf(
                        "loadFieldOptionData visibility condition records",
                        () => ({ model }),
                    );
                    const records = await this.visibilityConditionCachedRecords.read(
                        model,
                        [],
                        [idField, displayNameField],
                    );
                    endConditionRecords(() => ({ records: records.length }));
                    for (const record of records) {
                        conditionValueList.push({
                            value: String(record[idField]),
                            textContent: record[displayNameField],
                        });
                    }
                    if (!inputContainerEl.dataset.visibilityCondition) {
                        inputContainerEl.dataset.visibilityCondition = String(
                            records[0]?.[idField],
                        );
                    }
                } else {
                    const dependencyContainerEl = dependencyEl.closest(
                        ".s_website_form_field",
                    );
                    const inputsInDependencyContainer =
                        dependencyContainerEl.querySelectorAll(".s_website_form_input");
                    for (const el of inputsInDependencyContainer) {
                        conditionValueList.push({
                            value: el.value,
                            textContent:
                                inputsInDependencyContainer.length === 1
                                    ? el.value
                                    : dependencyContainerEl.querySelector(
                                          `label[for="${el.id}"]`,
                                      ).textContent,
                        });
                    }
                    if (!inputContainerEl.dataset.visibilityCondition) {
                        inputContainerEl.dataset.visibilityCondition =
                            inputsInDependencyContainer[0].value;
                    }
                }
                if (!inputContainerEl.dataset.visibilityComparator) {
                    inputContainerEl.dataset.visibilityComparator = "selected";
                }
            }
            if (!comparator) {
                if (dependencyEl.dataset.target) {
                    fieldEl.dataset.visibilityComparator = "after";
                } else if (
                    [
                        "text",
                        "email",
                        "tel",
                        "url",
                        "search",
                        "password",
                        "number",
                    ].includes(dependencyEl.type) ||
                    dependencyEl.nodeName === "TEXTAREA"
                ) {
                    fieldEl.dataset.visibilityComparator = "equal";
                } else if (dependencyEl.type === "file") {
                    fieldEl.dataset.visibilityComparator = "fileSet";
                }
            }
        }

        const currentFieldName = getFieldName(fieldEl);
        const fieldsInForm = Array.from(
            formEl.querySelectorAll(
                ".s_website_form_field:not(.s_website_form_custom) .s_website_form_input",
            ),
        )
            .map((el) => el.name)
            .filter((el) => el !== currentFieldName);
        const availableFields = existingFields.filter(
            (field) => !fieldsInForm.includes(field.name),
        );

        const selectEl = getSelect(fieldEl);
        const multipleInputsEl = getMultipleInputs(fieldEl);
        let valueList = undefined;
        if (selectEl || multipleInputsEl) {
            const field = Object.assign({}, fields[getFieldName(fieldEl)]);
            const type = getFieldType(fieldEl);

            const [optionText, checkType] = selectEl
                ? [_t("Option List"), "exclusive_boolean"]
                : type === "selection"
                  ? [_t("Radio Button List"), "exclusive_boolean"]
                  : [_t("Checkbox List"), "boolean"];
            const defaults = [...fieldEl.querySelectorAll("[checked], [selected]")].map(
                (el) => (isSmallInteger(el.value) ? parseInt(el.value) : el.value),
            );
            let availableRecords = undefined;
            if (!isFieldCustom(fieldEl)) {
                const endValueListRecords = log.perf(
                    "loadFieldOptionData value list records",
                    () => ({ name: field.name, type }),
                );
                await this.fetchFieldRecords(field);
                endValueListRecords();
                availableRecords = JSON.stringify(field.records);
            }
            valueList = reactive({
                title: optionText,
                addItemTitle: _t("Add New Option"),
                checkType,
                defaultItemName: _t("Item"),
                hasDefault: ["one2many", "many2many"].includes(type)
                    ? "multiple"
                    : "unique",
                defaults: JSON.stringify(defaults),
                availableRecords: availableRecords,
                newRecordId: isFieldCustom(fieldEl) ? getNewRecordId(fieldEl) : "",
                isInputDisabled: !isFieldCustom(fieldEl),
            });
        }
        log.pipeline("loadFieldOptionData", () => ({
            fields: Object.keys(fields).length,
            existingFields: existingFields.length,
            conditionInputs: conditionInputs.length,
            availableFields: availableFields.length,
            hasValueList: !!valueList,
            conditionValues: conditionValueList.length,
        }));
        return {
            fields,
            existingFields,
            conditionInputs,
            availableFields,
            valueList,
            conditionValueList,
        };
    }
    /**
     * @param {Object} params
     * @param {HTMLElement} params.snippetEl
     */
    async onSnippetDropped({ snippetEl }) {
        log.pipeline("onSnippetDropped", () => ({
            snippet: snippetEl.dataset.snippet,
        }));
        await this.rerenderFieldsInElement(snippetEl);
    }
    /**
     * @param {Object} params
     * @param {HTMLElement} params.cloneEl
     */
    async onCloned({ cloneEl }) {
        log.pipeline("onCloned", () => ({ className: cloneEl.className }));
        await this.rerenderFieldsInElement(cloneEl);

        this.removeSuccessMessagePreviews(cloneEl);
    }
    /**
     * @param {HTMLElement} rootEl
     */
    async rerenderFieldsInElement(rootEl) {
        const endRerender = log.perf("rerenderFieldsInElement", () => ({
            isField: rootEl.matches("[data-name='Field']:not(.s_website_form_dnone)"),
        }));
        if (rootEl.matches("[data-name='Field']:not(.s_website_form_dnone)")) {
            const { fields } = await this.loadFieldOptionData(rootEl);
            rerenderField(rootEl, fields);
        } else {
            for (const formEl of selectElements(rootEl, ".s_website_form")) {
                const formFieldsToRerender = formEl.querySelectorAll(
                    "[data-name='Field']:not(.s_website_form_dnone)",
                );
                if (formFieldsToRerender.length === 0) {
                    log.logic("rerenderFieldsInElement: form without fields, skipped");
                    continue;
                }
                log.pipeline("rerenderFieldsInElement form", () => ({
                    fields: formFieldsToRerender.length,
                }));
                const { fields } = await this.loadFieldOptionData(
                    formFieldsToRerender[0],
                );
                for (const fieldEl of formFieldsToRerender) {
                    rerenderField(fieldEl, fields);
                }
            }
        }
        endRerender();
    }
    /**
     * @param {HTMLElement} rootEl
     */
    removeSuccessMessagePreviews(rootEl) {
        const toCleanEls = rootEl.querySelectorAll(".o_show_form_success_message");
        log.pipeline("removeSuccessMessagePreviews", () => ({
            count: toCleanEls.length,
        }));
        toCleanEls.forEach((el) => el.classList.remove("o_show_form_success_message"));
    }
    /**
     * @params {HTMLElement} fieldEl
     */
    clearValidationDataset(fieldEl) {
        delete fieldEl.dataset.customError;
        delete fieldEl.dataset.errorMessage;
        delete fieldEl.dataset.requirementBetween;
        delete fieldEl.dataset.requirementCondition;
    }

    /**
     * @param {string} [comparator]
     * @param {string} [condition]
     * @param {string} [between]
     * @returns {string}
     */
    defaultMessage(comparator, condition, between, type) {
        const textMessages = {
            contains: _t("This field must include keyword %s.", condition),
            "!contains": _t("This field must not include keyword %s.", condition),
            substring: _t("This field must include keyword %s.", condition),
            "!substring": _t("This field must not include keyword %s.", condition),
            greater: _t("Invalid: field is not greater than %s.", condition),
            less: _t("Invalid: field is not less than %s.", condition),
            "greater or equal": _t(
                "Invalid: field is not greater than or equal to %s.",
                condition,
            ),
            "less or equal": _t(
                "Invalid: field is not less than or equal to %s.",
                condition,
            ),
        };

        if (condition && textMessages[comparator]) {
            return textMessages[comparator];
        }

        if (["date", "datetime"].includes(type)) {
            const format =
                type === "date" ? localization.dateFormat : localization.dateTimeFormat;
            const start = formatDate(DateTime.fromSeconds(parseInt(condition)), {
                format,
            });
            const end = formatDate(DateTime.fromSeconds(parseInt(between)), { format });

            const dateMessages = {
                dateEqual: _t(
                    "Entered date or time is not correct! It must be %(start)s (%(format)s).",
                    { start, format },
                ),
                "date!equal": _t(
                    "Entered date or time is not correct! It must not be %(start)s (%(format)s).",
                    { start, format },
                ),
                before: _t(
                    "Entered date or time is not correct! It must be before %(start)s (%(format)s).",
                    { start, format },
                ),
                after: _t(
                    "Entered date or time is not correct! It must be after %(start)s (%(format)s).",
                    { start, format },
                ),
                "equal or before": _t(
                    "Entered date or time is not correct! It must be before or equal to %(start)s (%(format)s).",
                    { start, format },
                ),
                "equal or after": _t(
                    "Entered date or time is not correct! It must be after or equal to %(start)s (%(format)s).",
                    { start, format },
                ),
                between: _t(
                    "Entered date or time is not correct! It must be within %(start)s and %(end)s (%(format)s).",
                    { start, end, format },
                ),
                "!between": _t(
                    "Entered date or time is not correct! It must not be within %(start)s and %(end)s (%(format)s).",
                    { start, end, format },
                ),
            };

            if (condition && dateMessages[comparator]) {
                return dateMessages[comparator];
            }
        }

        return _t("An error has occurred, the form has not been sent.");
    }
}

export class SelectAction extends BuilderAction {
    static id = "selectAction";
    static dependencies = ["websiteFormOption"];
    async load({ editingElement: el, value: modelId }) {
        const modelCantChange = !!el.getAttribute("hide-change-model");
        if (modelCantChange) {
            log.logic("SelectAction load: model cannot change", () => ({ modelId }));
            return;
        }
        const activeForm = this.dependencies.websiteFormOption
            .getModelsCache(el)
            .find((model) => model.id === parseInt(modelId));
        log.pipeline("SelectAction load", () => ({
            modelId,
            model: activeForm?.model,
        }));
        return {
            formInfo: await this.dependencies.websiteFormOption.prepareFormModel(
                el,
                activeForm,
            ),
        };
    }
    apply({ editingElement: el, value: modelId, loadResult }) {
        if (!loadResult) {
            log.logic("SelectAction apply: no load result, skipped", () => ({
                modelId,
            }));
            return;
        }
        const models = this.dependencies.websiteFormOption.getModelsCache(el);
        const targetModelName = getModelName(el);
        const activeForm = models.find((m) => m.model === targetModelName);
        log.pipeline("SelectAction apply", () => ({
            modelId,
            from: targetModelName,
            hasFormInfo: !!loadResult.formInfo,
        }));
        this.dependencies.websiteFormOption.applyFormModel(
            el,
            activeForm,
            parseInt(modelId),
            loadResult.formInfo,
        );
    }
    isApplied({ editingElement: el, value: modelId }) {
        const models = this.dependencies.websiteFormOption.getModelsCache(el);
        const targetModelName = getModelName(el);
        const activeForm = models.find((m) => m.model === targetModelName);
        return parseInt(modelId) === activeForm?.id;
    }
}
export class AddActionFieldAction extends BuilderAction {
    static id = "addActionField";
    static dependencies = ["websiteFormOption"];
    async load({ editingElement: el }) {
        log.pipeline("AddActionFieldAction load", () => ({
            model: el.dataset.model_name,
        }));
        return this.dependencies.websiteFormOption.fetchAuthorizedFields(el);
    }
    apply({ editingElement: el, value, params, loadResult: authorizedFields }) {
        for (const [fieldName, field] of Object.entries(authorizedFields)) {
            if (field._property) {
                for (const inputEl of el.querySelectorAll(`[name="${fieldName}"]`)) {
                    inputEl.closest(".s_website_form_field").remove();
                }
            }
        }
        const fieldName = params.fieldName;
        if (params.isSelect === "true") {
            value = parseInt(value);
        }
        log.pipeline("AddActionFieldAction apply", () => ({
            fieldName,
            value,
            authorizedFields: Object.keys(authorizedFields).length,
        }));
        this.dependencies.websiteFormOption.addHiddenField(el, value, fieldName);
    }
    getValue({ editingElement: el, params }) {
        const value = el.querySelector(
            `.s_website_form_dnone input[name="${params.fieldName}"]`,
        )?.value;
        if (params.fieldName === "email_to") {
            if (value && value !== DEFAULT_EMAIL_TO_VALUE) {
                return value;
            }
            const formId = el.id;
            const dataForValues = getParsedDataFor(formId, el.ownerDocument);
            return dataForValues?.["email_to"] || DEFAULT_EMAIL_TO_VALUE;
        }
        if (value) {
            return value;
        } else {
            return params.isSelect ? "0" : "";
        }
    }
    isApplied({ editingElement, params, value }) {
        const currentValue = this.getValue({
            editingElement,
            params,
        });
        return currentValue === value;
    }
}
export class PromptSaveRedirectAction extends BuilderAction {
    static id = "promptSaveRedirect";
    static dependencies = ["savePlugin"];
    setup() {
        this.canTimeout = false;
    }
    apply({ params: { mainParam } }) {
        const redirectToAction = (action) => {
            redirect(`/odoo/action-${encodeURIComponent(action)}`);
        };
        new Promise((resolve) => {
            const message = _t(
                "You are about to be redirected. Your changes will be saved.",
            );
            log.lifecycle("PromptSaveRedirectAction dialog open", () => ({
                action: mainParam,
            }));
            this.services.dialog.add(ConfirmationDialog, {
                body: message,
                confirmLabel: _t("Save and Redirect"),
                confirm: async () => {
                    log.logic("PromptSaveRedirectAction confirmed", () => ({
                        action: mainParam,
                    }));
                    const endSaveAndClose = log.perf(
                        "PromptSaveRedirectAction save and close",
                    );
                    await this.dependencies.savePlugin.save();
                    await this.config.closeEditor();
                    endSaveAndClose();
                    redirectToAction(mainParam);
                    resolve();
                },
                cancel: () => {
                    log.logic("PromptSaveRedirectAction cancelled", () => ({
                        action: mainParam,
                    }));
                    resolve();
                },
            });
        });
    }
}
export class UpdateLabelsMarkAction extends BuilderAction {
    static id = "updateLabelsMark";
    static dependencies = ["websiteFormOption"];
    apply({ editingElement: el }) {
        this.dependencies.websiteFormOption.setLabelsMark(el);
    }
    isApplied() {
        return true;
    }
}

export class SetMarkAction extends BuilderAction {
    static id = "setMark";
    static dependencies = ["websiteFormOption"];
    apply({ editingElement: el, value }) {
        el.dataset.mark = value.trim();
        this.dependencies.websiteFormOption.setLabelsMark(el);
    }
    getValue({ editingElement: el }) {
        const mark = getMark(el);
        return mark;
    }
}

export class OnSuccessAction extends BuilderAction {
    static id = "onSuccess";
    apply({ editingElement: el, value }) {
        el.dataset.successMode = value;
        let messageEl = el.parentElement.querySelector(".s_website_form_end_message");
        log.logic("OnSuccessAction apply", () => ({
            value,
            hasMessageEl: !!messageEl,
        }));
        if (value === "message") {
            if (!messageEl) {
                messageEl = renderToElement("website.s_website_form_end_message");
                el.insertAdjacentElement("afterend", messageEl);
            }
        } else {
            messageEl?.remove();
            messageEl?.classList.remove("o_show_form_success_message");
            el.classList.remove("o_show_form_success_message");
        }
    }
    isApplied({ editingElement: el, value }) {
        const currentValue = el.dataset.successMode;
        return currentValue === value;
    }
}
export class ToggleEndMessageAction extends BuilderAction {
    static id = "toggleEndMessage";
    static dependencies = ["builderOptions"];
    apply({ editingElement: el }) {
        const messageEl = el.parentElement.querySelector(".s_website_form_end_message");
        log.pipeline("ToggleEndMessageAction apply: show success message preview");
        messageEl.classList.add("o_show_form_success_message");
        el.classList.add("o_show_form_success_message");
        this.dependencies.builderOptions.setNextTarget(messageEl);
    }
    clean({ editingElement: el }) {
        const messageEl = el.parentElement.querySelector(".s_website_form_end_message");
        log.pipeline("ToggleEndMessageAction clean: hide success message preview");
        messageEl.classList.remove("o_show_form_success_message");
        el.classList.remove("o_show_form_success_message");
        this.dependencies.builderOptions.setNextTarget(el);
    }
    isApplied({ editingElement: el, value }) {
        return el.classList.contains("o_show_form_success_message");
    }
}
export class FormToggleRecaptchaLegalAction extends BuilderAction {
    static id = "formToggleRecaptchaLegal";
    apply({ editingElement: el }) {
        const labelWidth = el.querySelector(".s_website_form_label").style.width;
        const legalEl = renderToElement("website.s_website_form_recaptcha_legal", {
            labelWidth: labelWidth,
        });
        legalEl.setAttribute("contentEditable", true);
        log.pipeline("FormToggleRecaptchaLegalAction apply: legal inserted", () => ({
            labelWidth,
        }));
        el.querySelector(".s_website_form_submit").insertAdjacentElement(
            "beforebegin",
            legalEl,
        );
    }
    clean({ editingElement: el }) {
        const recaptchaLegalEl = el.querySelector(".s_website_form_recaptcha");
        log.pipeline("FormToggleRecaptchaLegalAction clean: legal removed");
        recaptchaLegalEl.remove();
    }
    isApplied({ editingElement: el }) {
        const recaptchaLegalEl = el.querySelector(".s_website_form_recaptcha");
        return !!recaptchaLegalEl;
    }
}
export class CustomFieldAction extends BuilderAction {
    static id = "customField";
    static dependencies = ["websiteFormOption"];
    load(context) {
        return this.dependencies.websiteFormOption.prepareFields(context);
    }
    apply({ editingElement: fieldEl, value, loadResult: fields }) {
        this.dependencies.websiteFormOption.clearValidationDataset(fieldEl);
        delete fieldEl.dataset.requirementComparator;
        const oldLabelText = fieldEl.querySelector(
            ".s_website_form_label_content",
        ).textContent;
        const field = getCustomField(value, oldLabelText);
        log.pipeline("CustomFieldAction apply", () => ({
            type: value,
            label: oldLabelText,
        }));
        setActiveProperties(fieldEl, field);
        this.dependencies.websiteFormOption.replaceField(fieldEl, field, fields);
    }
    isApplied({ editingElement: fieldEl, value }) {
        const currentValue = isFieldCustom(fieldEl) ? getFieldType(fieldEl) : "";
        return currentValue === value;
    }
}
export class ExistingFieldAction extends BuilderAction {
    static id = "existingField";
    static dependencies = ["websiteFormOption"];
    load(context) {
        return this.dependencies.websiteFormOption.prepareFields(context);
    }
    apply({ editingElement: fieldEl, value, loadResult: fields }) {
        const field = fields[value];
        log.logic("ExistingFieldAction apply", () => ({
            name: value,
            known: !!field,
        }));
        setActiveProperties(fieldEl, field);
        this.dependencies.websiteFormOption.replaceField(fieldEl, field, fields);
    }
    isApplied({ editingElement: fieldEl, value }) {
        const currentValue = isFieldCustom(fieldEl) ? "" : getFieldName(fieldEl);
        return currentValue === value;
    }
}
export class SelectTypeAction extends BuilderAction {
    static id = "selectType";
    static dependencies = ["websiteFormOption"];
    load(context) {
        return this.dependencies.websiteFormOption.prepareFields(context);
    }
    apply({ editingElement: fieldEl, value, loadResult: fields }) {
        const field = getActiveField(fieldEl, { fields });
        log.pipeline("SelectTypeAction apply", () => ({ from: field.type, to: value }));
        field.type = value;
        this.dependencies.websiteFormOption.replaceField(fieldEl, field, fields);
    }
    isApplied({ editingElement: fieldEl, value }) {
        const currentValue = getFieldType(fieldEl);
        return currentValue === value;
    }
}
export class ExistingFieldSelectTypeAction extends BuilderAction {
    static id = "existingFieldSelectType";
    static dependencies = ["websiteFormOption"];
    load(context) {
        return this.dependencies.websiteFormOption.prepareFields(context);
    }
    apply({ editingElement: fieldEl, value, loadResult: fields }) {
        const field = getActiveField(fieldEl, { fields });
        log.pipeline("ExistingFieldSelectTypeAction apply", () => ({
            name: field.name,
            from: field.type,
            to: value,
        }));
        field.type = value;
        this.dependencies.websiteFormOption.replaceField(fieldEl, field, fields);
    }
    isApplied({ editingElement: fieldEl, value }) {
        const currentValue = getFieldType(fieldEl);
        return currentValue === value;
    }
}
export class MultiCheckboxDisplayAction extends BuilderAction {
    static id = "multiCheckboxDisplay";
    apply({ editingElement: fieldEl, value }) {
        const targetEl = getMultipleInputs(fieldEl);
        const isHorizontal = value === "horizontal";
        log.pipeline("MultiCheckboxDisplayAction apply", () => ({
            value,
            inputs: targetEl.querySelectorAll(".checkbox, .radio").length,
        }));
        for (const el of targetEl.querySelectorAll(".checkbox, .radio")) {
            el.classList.toggle("col-lg-4", isHorizontal);
            el.classList.toggle("col-md-6", isHorizontal);
        }
        targetEl.dataset.display = value;
    }
    isApplied({ editingElement: fieldEl, value }) {
        const targetEl = getMultipleInputs(fieldEl);
        const currentValue = targetEl ? targetEl.dataset.display : "";
        return currentValue === value;
    }
}
export class SetLabelTextAction extends BuilderAction {
    static id = "setLabelText";
    static dependencies = ["websiteFormOption"];
    async apply({ editingElement: fieldEl, value }) {
        const labelEl = fieldEl.querySelector(".s_website_form_label_content");
        labelEl.textContent = value;
        log.logic("SetLabelTextAction apply", () => ({
            isCustom: isFieldCustom(fieldEl),
        }));
        if (isFieldCustom(fieldEl)) {
            value = getQuotesEncodedName(value);
            const multiple = fieldEl.querySelector(".s_website_form_multiple");
            if (multiple) {
                multiple.dataset.name = value;
            }
            const inputEls = fieldEl.querySelectorAll(".s_website_form_input");
            const previousInputName = inputEls[0].name;
            inputEls.forEach((el) => (el.name = value));

            const dependentEls = fieldEl.closest("form").querySelectorAll(
                `.s_website_form_field[data-visibility-dependency="${CSS.escape(
                    previousInputName,
                )}"],
                    .s_website_form_field[data-visibility-dependency="${CSS.escape(value)}"]`,
            );
            log.pipeline("SetLabelTextAction rename dependents", () => ({
                from: previousInputName,
                to: value,
                dependents: dependentEls.length,
            }));
            for (const dependentEl of dependentEls) {
                if (findCircular(fieldEl, dependentEl)) {
                    log.logic(
                        "SetLabelTextAction: circular dependency removed",
                        () => ({
                            dependent: dependentEl.dataset.name,
                        }),
                    );
                    deleteConditionalVisibility(dependentEl);
                } else {
                    dependentEl.dataset.visibilityDependency = value;
                }
            }
            const fieldWithVisibilityDependencyEls = [
                ...fieldEl
                    .closest("form")
                    .querySelectorAll("[data-visibility-dependency]"),
            ];
            const endRevalidate = log.perf(
                "SetLabelTextAction revalidate conditions",
                () => ({
                    fields: fieldWithVisibilityDependencyEls.length,
                }),
            );
            await Promise.all(
                fieldWithVisibilityDependencyEls.map(async (fieldWithConditionEl) => {
                    const conditionFieldName =
                        fieldWithConditionEl.dataset.visibilityDependency;
                    const fieldData =
                        await this.dependencies.websiteFormOption.loadFieldOptionData(
                            fieldWithConditionEl,
                        );
                    const names = fieldData.conditionInputs.map((entry) => entry.name);
                    if (!names.includes(conditionFieldName)) {
                        log.logic(
                            "SetLabelTextAction: condition no longer valid",
                            () => ({
                                conditionFieldName,
                            }),
                        );
                        deleteConditionalVisibility(fieldWithConditionEl);
                    }
                }),
            );
            endRevalidate();
        }
    }
    getValue({ editingElement: fieldEl }) {
        const labelEl = fieldEl.querySelector(".s_website_form_label_content");
        return labelEl.textContent;
    }
}
export class SelectLabelPositionAction extends BuilderAction {
    static id = "selectLabelPosition";
    static dependencies = ["websiteFormOption"];
    load(context) {
        return this.dependencies.websiteFormOption.prepareFields(context);
    }
    apply({ editingElement: fieldEl, value, loadResult: fields }) {
        const field = getActiveField(fieldEl, { fields });
        log.pipeline("SelectLabelPositionAction apply", () => ({
            from: field.formatInfo.labelPosition,
            to: value,
        }));
        field.formatInfo.labelPosition = value;
        this.dependencies.websiteFormOption.replaceField(fieldEl, field, fields);
    }
    isApplied({ editingElement: fieldEl, value }) {
        const currentValue = getLabelPosition(fieldEl);
        return currentValue === value;
    }
}
export class ToggleDescriptionAction extends BuilderAction {
    static id = "toggleDescription";
    static dependencies = ["websiteFormOption"];
    load(context) {
        return this.dependencies.websiteFormOption.prepareFields(context);
    }
    apply({ editingElement: fieldEl, loadResult: fields, value }) {
        const description = fieldEl.querySelector(".s_website_form_field_description");
        const hasDescription = !!description;
        const field = getActiveField(fieldEl, { fields });
        log.pipeline("ToggleDescriptionAction apply", () => ({
            show: !hasDescription,
        }));
        field.description = !hasDescription;
        this.dependencies.websiteFormOption.replaceField(fieldEl, field, fields);
    }
    isApplied({ editingElement: fieldEl }) {
        const description = fieldEl.querySelector(".s_website_form_field_description");
        return !!description;
    }
}
export class SelectTextareaValueAction extends BuilderAction {
    static id = "selectTextareaValue";
    apply({ editingElement: fieldEl, value }) {
        fieldEl.textContent = value;
        fieldEl.value = value;
    }
    getValue({ editingElement: fieldEl }) {
        return fieldEl.textContent;
    }
}
export class ToggleRequiredAction extends BuilderAction {
    static id = "toggleRequired";
    static dependencies = ["websiteFormOption"];
    apply({ editingElement: fieldEl, params: { mainParam: activeValue } }) {
        log.pipeline("ToggleRequiredAction apply", () => ({ activeValue }));
        fieldEl.classList.add(activeValue);
        fieldEl
            .querySelectorAll("input, select, textarea")
            .forEach((el) => el.toggleAttribute("required", true));
        this.dependencies.websiteFormOption.setLabelsMark(fieldEl.closest("form"));
    }
    clean({ editingElement: fieldEl, params: { mainParam: activeValue } }) {
        log.pipeline("ToggleRequiredAction clean", () => ({ activeValue }));
        fieldEl.classList.remove(activeValue);
        fieldEl
            .querySelectorAll("input, select, textarea")
            .forEach((el) => el.removeAttribute("required"));
        this.dependencies.websiteFormOption.setLabelsMark(fieldEl.closest("form"));
    }
    isApplied({ editingElement: fieldEl, params: { mainParam: activeValue } }) {
        return fieldEl.classList.contains(activeValue);
    }
}

export class SetRequirementComparatorAction extends BuilderAction {
    static id = "setRequirementComparator";
    static dependencies = ["websiteFormOption"];
    apply({ editingElement: fieldEl }) {
        this.dependencies.websiteFormOption.clearValidationDataset(fieldEl);
    }
}
export class SetCustomErrorMessageAction extends BuilderAction {
    static id = "setCustomErrorMessage";
    apply({ editingElement: fieldEl }) {
        log.logic("SetCustomErrorMessageAction apply", () => ({
            enable: !fieldEl.dataset.customError,
        }));
        if (!fieldEl.dataset.customError) {
            fieldEl.dataset.customError = true;
        } else {
            delete fieldEl.dataset.customError;
        }
    }
    isApplied({ editingElement: fieldEl }) {
        return fieldEl.dataset.customError;
    }
}
export class SetDefaultErrorMessageAction extends BuilderAction {
    static id = "setDefaultErrorMessage";
    static dependencies = ["websiteFormOption"];
    apply({ editingElement: fieldEl }) {
        const {
            requirementComparator: comparator,
            requirementCondition: condition,
            requirementBetween: between,
            type,
        } = fieldEl.dataset;
        log.logic("SetDefaultErrorMessageAction apply", () => ({
            comparator,
            type,
            hasCondition: !!condition,
        }));
        fieldEl.dataset.errorMessage =
            this.dependencies.websiteFormOption.defaultMessage(
                comparator,
                condition,
                between,
                type,
            );
    }
}

export class SetVisibilityAction extends BuilderAction {
    static id = "setVisibility";
    static dependencies = ["websiteFormOption"];
    load(context) {
        return this.dependencies.websiteFormOption.prepareConditionInputs(context);
    }
    apply({ editingElement: fieldEl, value, loadResult: conditionInputs }) {
        if (value === "conditional") {
            for (const conditionInput of conditionInputs) {
                if (conditionInput.name) {
                    log.logic(
                        "SetVisibilityAction apply: conditional on first input",
                        () => ({
                            dependency: conditionInput.name,
                        }),
                    );
                    setVisibilityDependency(fieldEl, conditionInput.name);
                    return;
                }
            }
            log.logic(
                "SetVisibilityAction apply: no condition input available",
                () => ({
                    conditionInputs: conditionInputs.length,
                }),
            );
            this.services.dialog.add(ConfirmationDialog, {
                body: _t("There is no field available for this option."),
            });
        }
        log.logic("SetVisibilityAction apply: clear conditional visibility", () => ({
            value,
        }));
        deleteConditionalVisibility(fieldEl);
    }
    isApplied() {
        return true;
    }
}
export class SetVisibilityDependencyAction extends BuilderAction {
    static id = "setVisibilityDependency";
    apply({ editingElement: fieldEl, value }) {
        log.pipeline("SetVisibilityDependencyAction apply", () => ({
            dependency: value,
        }));
        return setVisibilityDependency(fieldEl, value);
    }
    isApplied({ editingElement: fieldEl, value }) {
        const currentValue = fieldEl.dataset.visibilityDependency || "";
        return currentValue === value;
    }
}
export class SetFormCustomFieldValueListAction extends BuilderAction {
    static id = "setFormCustomFieldValueList";
    static dependencies = ["websiteFormOption"];
    load(context) {
        return this.dependencies.websiteFormOption.prepareFields(context);
    }
    apply({ editingElement: fieldEl, value, loadResult: fields }) {
        let valueList = JSON.parse(value);
        if (isFieldCustom(fieldEl)) {
            // A custom field posts its labels, so each value follows its label.
            valueList = valueList.map((record) => ({
                ...record,
                id: isSmallInteger(record.display_name)
                    ? parseInt(record.display_name)
                    : record.display_name,
            }));
        }
        if (getSelect(fieldEl)) {
            valueList = valueList.filter(
                (value) => value.id !== "" || value.display_name !== "",
            );
            const hasDefault = valueList.some((value) => value.selected);
            if (valueList.length && !hasDefault) {
                log.logic(
                    "SetFormCustomFieldValueListAction: prepend empty default option",
                );
                valueList.unshift({
                    id: "",
                    display_name: "",
                    selected: true,
                });
            }
        }
        const field = getActiveField(fieldEl, { fields });
        log.pipeline("SetFormCustomFieldValueListAction apply", () => ({
            isCustom: isFieldCustom(fieldEl),
            records: valueList.length,
        }));
        field.records = valueList;
        this.dependencies.websiteFormOption.replaceField(fieldEl, field, fields);
    }
    getValue({ editingElement: fieldEl }) {
        const fields = [];
        const field = getActiveField(fieldEl, { fields });
        if (
            field.records.length &&
            field.records[0].display_name === "" &&
            field.records[0].selected === true
        ) {
            field.records.shift();
        }
        return JSON.stringify(field.records);
    }
}
class PropertyAction extends BuilderAction {
    static id = "property";

    apply({ editingElement, params: { property, format } = {}, value }) {
        editingElement[property] = format ? format(value) : value;
    }
}
class SetMultipleFilesAction extends BuilderAction {
    static id = "setMultipleFiles";
    apply({ editingElement }) {
        editingElement.multiple = editingElement.dataset.maxFilesNumber > 1;
    }
}

registry.category("website-plugins").add(FormOptionPlugin.id, FormOptionPlugin);
