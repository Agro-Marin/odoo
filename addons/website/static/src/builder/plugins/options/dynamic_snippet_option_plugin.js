/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { SNIPPET_SPECIFIC_END } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { Cache } from "@web/core/utils/collections/cache";

import { DynamicSnippetOption } from "./dynamic_snippet_option.js";

const log = makeLogger("website.builder.plugin.dynamic_snippet_option");

/**
 * @typedef {object} Template
 * @property {string} arrowPosition
 * @property {string} columnClasses
 * @property {string} containerClasses
 * @property {string} contentClasses
 * @property {string} extraClasses
 * @property {string} extraSnippetClasses
 * @property {string} key
 * @property {string} numberOfElements
 * @property {string} numberOfElementsSmallDevices
 * @property {string} numberOfRecords
 * @property {string} rowPerSlide
 * @property {string} thumb
 */

/**
 * @typedef { Object } DynamicSnippetOptionShared
 * @property { DynamicSnippetOptionPlugin['fetchDynamicFilters'] } fetchDynamicFilters
 * @property { DynamicSnippetOptionPlugin['fetchDynamicSnippetTemplates'] } fetchDynamicSnippetTemplates
 * @property { DynamicSnippetOptionPlugin['getDefaultSnippetFilterId'] } getDefaultSnippetFilterId
 * @property { DynamicSnippetOptionPlugin['getDefaultSnippetRecordId'] } getDefaultSnippetRecordId
 * @property { DynamicSnippetOptionPlugin['getDefaultSnippetTemplate'] } getDefaultSnippetTemplate
 * @property { DynamicSnippetOptionPlugin['getSnippetModelName'] } getSnippetModelName
 * @property { DynamicSnippetOptionPlugin['getSnippetTitleClasses'] } getSnippetTitleClasses
 * @property { DynamicSnippetOptionPlugin['getTemplateByKey'] } getTemplateByKey
 * @property { DynamicSnippetOptionPlugin['isModelSnippetTemplate'] } isModelSnippetTemplate
 * @property { DynamicSnippetOptionPlugin['isSingleModeSnippet'] } isSingleModeSnippet
 * @property { DynamicSnippetOptionPlugin['isSingleModeSnippetTemplate'] } isSingleModeSnippetTemplate
 * @property { DynamicSnippetOptionPlugin['setOptionsDefaultValues'] } setOptionsDefaultValues
 * @property { DynamicSnippetOptionPlugin['updateTemplate'] } updateTemplate
 * @property { DynamicSnippetOptionPlugin['getModelNameFilter'] } getModelNameFilter
 */

/**
 * @typedef {((arg: { el: HTMLElement; template: Template; }) => void)[]} dynamic_snippet_template_updated
 */

export const DYNAMIC_SNIPPET = SNIPPET_SPECIFIC_END;
export const CONTAINER_CLASSES = ["container", "container-fluid", "o_container_small"];

class DynamicSnippetOptionPlugin extends Plugin {
    static id = "dynamicSnippetOption";
    static shared = [
        "fetchDynamicFilters",
        "fetchDynamicSnippetTemplates",
        "getDefaultSnippetFilterId",
        "getDefaultSnippetRecordId",
        "getDefaultSnippetTemplate",
        "getSnippetModelName",
        "getSnippetTitleClasses",
        "getTemplateByKey",
        "isModelSnippetTemplate",
        "isSingleModeSnippet",
        "isSingleModeSnippetTemplate",
        "setOptionsDefaultValues",
        "updateTemplate",
        "getModelNameFilter",
    ];
    modelNameFilter = "";
    fetchedDynamicFilters = [];
    fetchedDynamicFilterTemplates = [];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(DYNAMIC_SNIPPET, DynamicSnippetOption)],
        builder_actions: {
            DynamicFilterAction,
            DynamicSnippetTemplateAction,
            DynamicModelAction,
            DynamicRecordAction,
            CustomizeTemplateAction,
            NumberOfRecordsAction,
        },
        on_snippet_dropped_handlers: this.onSnippetDropped.bind(this),
        is_unremovable_selector: ".s_dynamic_snippet_title",
    };
    setup() {
        this.dynamicFiltersCache = new Cache(this._fetchDynamicFilters, JSON.stringify);
        this.dynamicFilterTemplatesCache = new Cache(
            this._fetchDynamicSnippetTemplates,
            JSON.stringify,
        );
        log.lifecycle("DynamicSnippetOptionPlugin setup: caches created");
    }
    destroy() {
        super.destroy();
        log.lifecycle("DynamicSnippetOptionPlugin destroy: caches invalidated");
        this.dynamicFiltersCache.invalidate();
        this.dynamicFilterTemplatesCache.invalidate();
    }
    getModelNameFilter() {
        return this.modelNameFilter;
    }
    async onSnippetDropped({ snippetEl }) {
        if (snippetEl.matches(DynamicSnippetOption.selector)) {
            log.logic(
                "DynamicSnippetOptionPlugin snippet dropped: set default values",
                () => ({
                    snippet: snippetEl.dataset.snippet,
                }),
            );
            await this.setOptionsDefaultValues(snippetEl, this.modelNameFilter);
        }
        if (snippetEl.classList.contains("s_dynamic")) {
            log.logic("DynamicSnippetOptionPlugin snippet dropped: mark loading");
            snippetEl.classList.remove("o_dynamic_snippet_empty");
            snippetEl.classList.add("o_dynamic_snippet_loading");
        }
    }
    async setOptionsDefaultValues(
        snippetEl,
        modelNameFilter,
        contextualFilterDomain = [],
    ) {
        const endFetch = log.perf(
            "DynamicSnippetOptionPlugin setOptionsDefaultValues fetch",
            () => ({
                modelNameFilter,
            }),
        );
        await this.fetchDynamicFilters({
            model_name: modelNameFilter,
            search_domain: contextualFilterDomain,
        });
        await this.fetchDynamicSnippetTemplates(modelNameFilter);
        endFetch(() => ({
            filters: this.fetchedDynamicFilters.length,
            templates: this.fetchedDynamicFilterTemplates.length,
        }));

        const dynamicFilters = {};
        for (const dynamicFilter of this.fetchedDynamicFilters) {
            dynamicFilters[dynamicFilter.id] = dynamicFilter;
        }
        const dynamicFilterTemplates = {};
        for (const dynamicFilterTemplate of this.fetchedDynamicFilterTemplates) {
            dynamicFilterTemplates[dynamicFilterTemplate.key] = dynamicFilterTemplate;
        }
        const defaultModelName =
            modelNameFilter || this.fetchedDynamicFilters[0]?.model_name;
        const isSingleMode = this.isSingleModeSnippet({
            ...snippetEl.dataset,
            snippetModel: defaultModelName,
        });
        let defaultTemplate = this.fetchedDynamicFilterTemplates.find((template) =>
            snippetEl.classList.contains(this.getTemplateClass(template.key)),
        );
        if (!defaultTemplate) {
            log.logic(
                "DynamicSnippetOptionPlugin no template class on snippet: use default",
            );
            defaultTemplate = this.getDefaultSnippetTemplate(
                defaultModelName,
                isSingleMode,
            );
        }
        log.logic("DynamicSnippetOptionPlugin setOptionsDefaultValues mode", () => ({
            isSingleMode,
            defaultModelName,
            defaultTemplate: defaultTemplate?.key,
        }));
        if (isSingleMode) {
            if (defaultModelName) {
                setDatasetIfUndefined(snippetEl, "snippetModel", defaultModelName);
            }
            const defaultSnippetRecordId =
                await this.getDefaultSnippetRecordId(defaultModelName);
            if (defaultSnippetRecordId) {
                setDatasetIfUndefined(
                    snippetEl,
                    "snippetResId",
                    defaultSnippetRecordId,
                );
            }
            setDatasetIfUndefined(snippetEl, "templateKey", defaultTemplate.key);
            this.updateTemplate(snippetEl, defaultTemplate);
        } else {
            let selectedFilterId = snippetEl.dataset["filterId"];
            if (Object.keys(dynamicFilters).length > 0) {
                if (!snippetEl.dataset.numberOfRecords) {
                    snippetEl.dataset["numberOfRecords"] =
                        this.fetchedDynamicFilters[0].limit;
                }
                const defaultFilterId = this.fetchedDynamicFilters[0].id;
                if (!dynamicFilters[selectedFilterId]) {
                    log.logic(
                        "DynamicSnippetOptionPlugin selected filter unavailable: use default",
                        () => ({
                            selectedFilterId,
                            defaultFilterId,
                        }),
                    );
                    snippetEl.dataset["filterId"] = defaultFilterId;
                    selectedFilterId = defaultFilterId;
                }
            }
            if (
                dynamicFilters[selectedFilterId] &&
                !dynamicFilterTemplates[snippetEl.dataset["templateKey"]]
            ) {
                log.logic(
                    "DynamicSnippetOptionPlugin template missing for filter: use default",
                    () => ({
                        templateKey: snippetEl.dataset["templateKey"],
                        defaultTemplate: defaultTemplate.key,
                    }),
                );
                snippetEl.dataset["templateKey"] = defaultTemplate.key;
                this.updateTemplate(snippetEl, defaultTemplate);
            }
        }
    }
    getTemplateByKey(templateKey) {
        return (
            templateKey &&
            this.fetchedDynamicFilterTemplates.find(({ key }) => key === templateKey)
        );
    }
    getTemplateClass(templateKey) {
        return templateKey.replace(/.*\.dynamic_filter_template_/, "s_");
    }
    updateTemplate(el, template) {
        const newTemplateKey = template.key;
        const oldTemplateKey = el.dataset.templateKey;
        const oldTemplate = this.getTemplateByKey(oldTemplateKey);
        log.pipeline("DynamicSnippetOptionPlugin updateTemplate", () => ({
            from: oldTemplateKey,
            to: newTemplateKey,
            knownOldTemplate: !!oldTemplate,
        }));
        el.dataset.templateKey = newTemplateKey;
        if (oldTemplateKey) {
            el.classList.remove(this.getTemplateClass(oldTemplateKey));
        }
        el.classList.add(this.getTemplateClass(newTemplateKey));

        if (template.numOfEl) {
            el.dataset.numberOfElements = template.numOfEl;
        } else {
            delete el.dataset.numberOfElements;
        }
        if (template.numOfElSm) {
            el.dataset.numberOfElementsSmallDevices = template.numOfElSm;
        } else {
            delete el.dataset.numberOfElementsSmallDevices;
        }
        if (template.numOfElFetch) {
            el.dataset.numberOfRecords = template.numOfElFetch;
        }
        if (template.extraClasses) {
            el.dataset.extraClasses = template.extraClasses;
        } else {
            delete el.dataset.extraClasses;
        }
        if (template.columnClasses) {
            el.dataset.columnClasses = template.columnClasses;
        } else {
            delete el.dataset.columnClasses;
        }
        if (oldTemplate) {
            const snippetContainerEl = el.querySelector(".s_dynamic_snippet_container");
            const snippetContentEl = el.querySelector(".s_dynamic_snippet_content");
            snippetContainerEl.classList.remove(...CONTAINER_CLASSES);
            snippetContainerEl.classList.add(
                ...(template.containerClasses || "container").split(" "),
            );
            snippetContentEl.classList.remove(
                ...(oldTemplate.contentClasses?.split(" ") || []),
            );
            snippetContentEl.classList.add(
                ...(template.contentClasses?.split(" ") || []),
            );
            el.classList.remove(...(oldTemplate.extraSnippetClasses?.split(" ") || []));
            el.classList.add(...(template.extraSnippetClasses?.split(" ") || []));
        }
        this.dispatchTo("dynamic_snippet_template_updated", {
            el: el,
            template: template,
        });
    }
    async fetchDynamicFilters(params) {
        const endRead = log.perf(
            "DynamicSnippetOptionPlugin fetchDynamicFilters",
            () => ({
                params,
            }),
        );
        this.fetchedDynamicFilters = await this.dynamicFiltersCache.read(params);
        endRead(() => ({ filters: this.fetchedDynamicFilters.length }));
        return this.fetchedDynamicFilters;
    }
    async _fetchDynamicFilters(params) {
        log.logic("DynamicSnippetOptionPlugin filters cache miss: rpc", () => ({
            params,
        }));
        return rpc("/website/snippet/options_filters", params);
    }
    async fetchDynamicSnippetTemplates(modelName) {
        const endRead = log.perf(
            "DynamicSnippetOptionPlugin fetchDynamicSnippetTemplates",
            () => ({
                modelName,
            }),
        );
        this.fetchedDynamicFilterTemplates =
            await this.dynamicFilterTemplatesCache.read({
                filter_name: modelName.replaceAll(".", "_"),
            });
        endRead(() => ({ templates: this.fetchedDynamicFilterTemplates.length }));
        return this.fetchedDynamicFilterTemplates;
    }
    async _fetchDynamicSnippetTemplates(params) {
        log.logic("DynamicSnippetOptionPlugin templates cache miss: rpc", () => ({
            params,
        }));
        return rpc("/website/snippet/filter_templates", params);
    }
    isSingleModeSnippet({ numberOfRecords, ...params }) {
        return !!(
            parseInt(numberOfRecords) === 1 &&
            this.getDefaultSnippetTemplate(this.getSnippetModelName(params), true) &&
            !params.carouselInterval
        );
    }
    isSingleModeSnippetTemplate(key) {
        return key.includes("_single_");
    }
    isModelSnippetTemplate(key, modelName) {
        return key.includes(`_${modelName.replaceAll(".", "_")}_`);
    }
    getDefaultSnippetTemplate(modelName, singleMode) {
        if (modelName) {
            return this.fetchedDynamicFilterTemplates.find((template) => {
                const isSingleTemplate = this.isSingleModeSnippetTemplate(template.key);
                return (
                    this.isModelSnippetTemplate(template.key, modelName) &&
                    (singleMode ? isSingleTemplate : !isSingleTemplate)
                );
            });
        }
    }
    async getDefaultSnippetRecordId(modelName) {
        const endSearch = log.perf(
            "DynamicSnippetOptionPlugin getDefaultSnippetRecordId",
            () => ({
                modelName,
            }),
        );
        const defaultRecrod = await this.services.orm.searchRead(
            modelName,
            [["is_published", "=", true]],
            ["id"],
            { limit: 1 },
        );
        endSearch(() => ({ found: !!defaultRecrod[0] }));
        return defaultRecrod[0]?.id || "";
    }
    getDefaultSnippetFilterId(modelName) {
        return (
            this.fetchedDynamicFilters.find(
                ({ model_name }) => model_name === modelName,
            )?.id || ""
        );
    }
    getSnippetModelName(snippetData) {
        return (
            snippetData.snippetModel ||
            this.fetchedDynamicFilters.find(
                ({ id }) => id === parseInt(snippetData.filterId),
            )?.model_name
        );
    }
    getSnippetTitleClasses(position) {
        const classes = {
            left: "d-flex justify-content-between s_dynamic_snippet_title_aside col-lg-3 flex-lg-column justify-content-lg-start",
            top: "d-flex justify-content-between",
            none: "d-none",
        };
        return position ? classes[position] : classes;
    }
}

export class DynamicFilterAction extends BuilderAction {
    static id = "dynamicFilter";
    static dependencies = ["dynamicSnippetOption"];
    isApplied({ editingElement: el, params }) {
        return parseInt(el.dataset.filterId) === params.id;
    }
    async apply({ editingElement: el, params }) {
        const utils = this.dependencies.dynamicSnippetOption;
        let defaultTemplate = params.defaultTemplate;
        log.pipeline("DynamicFilterAction apply", () => ({
            filterId: params.id,
            model: params.model_name,
        }));
        el.dataset.filterId = params.id;
        if (
            !el.dataset.templateKey ||
            !utils.isModelSnippetTemplate(el.dataset.templateKey, params.model_name)
        ) {
            log.logic("DynamicFilterAction template does not fit filter model", () => ({
                templateKey: el.dataset.templateKey,
                model: params.model_name,
            }));
            if (utils.isSingleModeSnippet(el.dataset)) {
                log.logic("DynamicFilterAction single mode: switch to model record");
                el.dataset.snippetModel = params.model_name;
                delete el.dataset.filterId;
                defaultTemplate = utils.getDefaultSnippetTemplate(
                    params.model_name,
                    true,
                );
                el.dataset.snippetResId = await utils.getDefaultSnippetRecordId(
                    params.model_name,
                );
            }
            utils.updateTemplate(el, defaultTemplate);
        }
    }
}
export class DynamicSnippetTemplateAction extends BuilderAction {
    static id = "dynamicSnippetTemplate";
    static dependencies = ["dynamicSnippetOption"];
    isApplied({ editingElement: el, params }) {
        return el.dataset.templateKey === params.key;
    }
    apply({ editingElement: el, params }) {
        log.pipeline("DynamicSnippetTemplateAction apply", () => ({ key: params.key }));
        this.dependencies.dynamicSnippetOption.updateTemplate(el, params);
    }
}
export class CustomizeTemplateAction extends BuilderAction {
    static id = "customizeTemplate";
    isApplied({ editingElement: el, params: { mainParam: customDataKey } }) {
        const customData = JSON.parse(el.dataset.customTemplateData);
        return customData[customDataKey];
    }
    apply({ editingElement: el, params: { mainParam: customDataKey }, value }) {
        const customData = JSON.parse(el.dataset.customTemplateData);
        log.pipeline("CustomizeTemplateAction apply", () => ({ customDataKey }));
        customData[customDataKey] = true;
        el.dataset.customTemplateData = JSON.stringify(customData);
    }
    clean({ editingElement: el, params: { mainParam: customDataKey }, value }) {
        const customData = JSON.parse(el.dataset.customTemplateData);
        log.pipeline("CustomizeTemplateAction clean", () => ({ customDataKey }));
        customData[customDataKey] = false;
        el.dataset.customTemplateData = JSON.stringify(customData);
    }
}
export class DynamicModelAction extends BuilderAction {
    static id = "dynamicModel";
    static dependencies = ["dynamicSnippetOption"];
    isApplied({ editingElement: el, params }) {
        return el.dataset.snippetModel === params.mainParam;
    }
    async apply({ editingElement: el, params: { mainParam: modelName } }) {
        const utils = this.dependencies.dynamicSnippetOption;
        if (el.dataset.snippetModel !== modelName) {
            log.logic("DynamicModelAction switch model", () => ({
                from: el.dataset.snippetModel,
                to: modelName,
            }));
            el.dataset.snippetModel = modelName;
            el.dataset.snippetResId = await utils.getDefaultSnippetRecordId(modelName);
            utils.updateTemplate(el, utils.getDefaultSnippetTemplate(modelName, true));
        }
    }
}
export class DynamicRecordAction extends BuilderAction {
    static id = "dynamicRecord";
    getValue({ editingElement }) {
        const id = editingElement.dataset.snippetResId;
        if (id) {
            return JSON.stringify({ id: parseInt(id) });
        }
    }
    apply({ editingElement, value }) {
        const { id } = JSON.parse(value);
        log.pipeline("DynamicRecordAction apply", () => ({ id }));
        editingElement.dataset.snippetResId = id;
    }
}
export class NumberOfRecordsAction extends BuilderAction {
    static id = "numberOfRecords";
    static dependencies = ["dynamicSnippetOption", "builderActions"];

    setup() {
        this.defaultRecordId = "";
        this.previousTemplate = false;
        this.utils = this.dependencies.dynamicSnippetOption;
    }
    async load({ editingElement }) {
        this.modelName = this.utils.getSnippetModelName(editingElement.dataset);
        log.pipeline("NumberOfRecordsAction load", () => ({
            modelName: this.modelName,
        }));
        this.defaultRecordId = await this.utils.getDefaultSnippetRecordId(
            this.modelName,
        );
    }
    isApplied({ editingElement: el, params }) {
        return el.dataset.numberOfRecords === params.mainParam;
    }
    apply({ editingElement: el, params }) {
        const isSingleModeBefore = this.utils.isSingleModeSnippet(el.dataset);
        el.dataset.numberOfRecords = params.mainParam;
        const isSingleModeAfter = this.utils.isSingleModeSnippet(el.dataset);
        const switchMode = isSingleModeBefore !== isSingleModeAfter;
        log.logic("NumberOfRecordsAction apply", () => ({
            numberOfRecords: params.mainParam,
            isSingleModeBefore,
            isSingleModeAfter,
        }));
        if (switchMode) {
            const canUsePreviousTemplate =
                !!this.previousTemplate &&
                this.utils.isModelSnippetTemplate(
                    this.previousTemplate.key,
                    this.modelName,
                ) &&
                !!this.utils.isSingleModeSnippetTemplate(this.previousTemplate.key) ===
                    isSingleModeAfter;
            const newModeDefaultTemplate = !canUsePreviousTemplate
                ? this.utils.getDefaultSnippetTemplate(
                      this.modelName,
                      isSingleModeAfter,
                  )
                : this.previousTemplate;
            log.logic("NumberOfRecordsAction switch mode template", () => ({
                canUsePreviousTemplate,
                template: newModeDefaultTemplate?.key,
            }));
            this.previousTemplate = this.utils.getTemplateByKey(el.dataset.templateKey);
            if (isSingleModeAfter) {
                delete el.dataset.filterId;
                el.dataset.snippetModel = this.modelName;
                el.dataset.snippetResId = this.defaultRecordId;
            } else {
                el.dataset.filterId = this.utils.getDefaultSnippetFilterId(
                    this.modelName,
                );
                delete el.dataset.snippetModel;
                delete el.dataset.snippetResId;
            }
            const titleEl = el.querySelector(".s_dynamic_snippet_title");
            const classAction =
                this.dependencies.builderActions.getAction("classAction");
            const titleClasses = Object.values(
                this.utils.getSnippetTitleClasses(),
            ).find((classes) =>
                titleEl.matches(
                    classes
                        .split(" ")
                        .map((c) => "." + c)
                        .join(""),
                ),
            );
            classAction.clean({
                editingElement: titleEl,
                params: { mainParam: titleClasses },
            });
            classAction.apply({
                editingElement: titleEl,
                params: {
                    mainParam: this.utils.getSnippetTitleClasses(
                        isSingleModeAfter ? "none" : "top",
                    ),
                },
            });
            return this.utils.updateTemplate(el, newModeDefaultTemplate);
        }
    }
}

export function setDatasetIfUndefined(snippetEl, optionName, value) {
    if (snippetEl.dataset[optionName] === undefined) {
        snippetEl.dataset[optionName] = value;
    }
}

registry
    .category("website-plugins")
    .add(DynamicSnippetOptionPlugin.id, DynamicSnippetOptionPlugin);
