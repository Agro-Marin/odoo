/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

import { DynamicSnippetCarouselOption } from "./dynamic_snippet_carousel_option.js";
import {
    DYNAMIC_SNIPPET,
    setDatasetIfUndefined,
} from "./dynamic_snippet_option_plugin.js";

const log = makeLogger("website.builder.plugin.dynamic_snippet_carousel_option");

/**
 * @typedef { Object } DynamicSnippetCarouselOptionShared
 * @property { DynamicSnippetCarouselOptionPlugin['setOptionsDefaultValues'] } setOptionsDefaultValues
 * @property { DynamicSnippetCarouselOptionPlugin['updateTemplateSnippetCarousel'] } updateTemplateSnippetCarousel
 * @property { DynamicSnippetCarouselOptionPlugin['getModelNameFilter'] } getModelNameFilter
 */

export const DYNAMIC_SNIPPET_CAROUSEL = DYNAMIC_SNIPPET;

class DynamicSnippetCarouselOptionPlugin extends Plugin {
    static id = "dynamicSnippetCarouselOption";
    static shared = [
        "setOptionsDefaultValues",
        "updateTemplateSnippetCarousel",
        "getModelNameFilter",
    ];
    static dependencies = ["dynamicSnippetOption"];
    modelNameFilter = "";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_actions: {
            SetCarouselSliderSpeedAction,
        },
        builder_options: withSequence(
            DYNAMIC_SNIPPET_CAROUSEL,
            DynamicSnippetCarouselOption,
        ),
        dynamic_snippet_template_updated: this.onTemplateUpdated.bind(this),
        on_snippet_dropped_handlers: this.onSnippetDropped.bind(this),
    };
    getModelNameFilter() {
        return this.modelNameFilter;
    }
    onTemplateUpdated({ el, template }) {
        if (el.matches(DynamicSnippetCarouselOption.selector)) {
            this.updateTemplateSnippetCarousel(el, template);
        }
    }
    updateTemplateSnippetCarousel(el, template) {
        log.pipeline("DynamicSnippetCarouselOptionPlugin update template", () => ({
            rowPerSlide: template.rowPerSlide,
            arrowPosition: template.arrowPosition,
        }));
        if (template.rowPerSlide) {
            el.dataset.rowPerSlide = template.rowPerSlide;
        } else {
            delete el.dataset.rowPerSlide;
        }
        if (template.arrowPosition) {
            el.dataset.arrowPosition = template.arrowPosition;
        } else {
            delete el.dataset.arrowPosition;
        }
    }
    async onSnippetDropped({ snippetEl }) {
        if (snippetEl.matches(DynamicSnippetCarouselOption.selector)) {
            log.logic("DynamicSnippetCarouselOptionPlugin snippet dropped", () => ({
                snippet: snippetEl.dataset.snippet,
            }));
            await this.setOptionsDefaultValues(snippetEl, this.modelNameFilter);
        }
    }
    async setOptionsDefaultValues(
        snippetEl,
        modelNameFilter,
        contextualFilterDomain = [],
    ) {
        const endDefaults = log.perf(
            "DynamicSnippetCarouselOptionPlugin setOptionsDefaultValues",
            () => ({
                modelNameFilter,
            }),
        );
        await this.dependencies.dynamicSnippetOption.setOptionsDefaultValues(
            snippetEl,
            modelNameFilter,
            contextualFilterDomain,
        );
        endDefaults();
        setDatasetIfUndefined(snippetEl, "carouselInterval", "5000");
    }
}

export class SetCarouselSliderSpeedAction extends BuilderAction {
    static id = "setCarouselSliderSpeed";
    apply({ editingElement, value }) {
        editingElement.dataset.carouselInterval = value * 1000;
    }
    getValue({ editingElement }) {
        return editingElement.dataset.carouselInterval === undefined
            ? undefined
            : editingElement.dataset.carouselInterval / 1000;
    }
}

registry
    .category("website-plugins")
    .add(DynamicSnippetCarouselOptionPlugin.id, DynamicSnippetCarouselOptionPlugin);
